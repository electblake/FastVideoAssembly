"""CLAP classification worker, emitting one saved score per source clip."""

import gc
import json
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock, local
from time import sleep

from ffmpeg import FFmpeg

MODEL_ID = "Xenova/clap-htsat-unfused"
MODEL_FILE = "onnx/model_fp16.onnx"
GPU_MODEL_ID = "laion/clap-htsat-unfused"
BACKGROUND_LABELS = ["environmental sounds", "silence"]
WINDOW_SECONDS = 10


def create_classifier(device, precision, gpu_index, cache_dir):
    import numpy as np
    import torch
    from huggingface_hub import hf_hub_download
    from transformers import (
        ClapConfig,
        ClapModel,
        ClapProcessor,
        PreTrainedModel,
        pipeline,
    )
    from transformers.utils import ModelOutput

    if device == "cuda":
        processor = ClapProcessor.from_pretrained(GPU_MODEL_ID, cache_dir=cache_dir)
        dtype = {"float16": torch.float16, "float32": torch.float32}[precision]
        model = ClapModel.from_pretrained(GPU_MODEL_ID, cache_dir=cache_dir, dtype=dtype,
                                         use_safetensors=False)
        return pipeline(
            task="zero-shot-audio-classification", model=model.eval(),
            tokenizer=processor.tokenizer, feature_extractor=processor.feature_extractor,
            device=f"cuda:{gpu_index}", dtype=dtype,
        )

    import onnxruntime as ort

    class OnnxClapModel(PreTrainedModel):
        config_class = ClapConfig
        main_input_name = "input_features"
        input_modalities = ("audio", "text")

        def __init__(self):
            super().__init__(ClapConfig.from_pretrained(MODEL_ID, cache_dir=cache_dir))
            self._device_anchor = torch.nn.Parameter(torch.empty(0), requires_grad=False)
            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            self.session = ort.InferenceSession(
                hf_hub_download(MODEL_ID, MODEL_FILE, cache_dir=cache_dir), sess_options=options,
                providers=["CPUExecutionProvider"]
            )

        def forward(self, input_ids, input_features, attention_mask, **kwargs):
            (logits,) = self.session.run(
                ["logits_per_audio"],
                {"input_ids": input_ids.cpu().numpy(),
                 "input_features": input_features.cpu().numpy(),
                 "attention_mask": attention_mask.cpu().numpy()},
            )
            return ModelOutput(logits_per_audio=torch.from_numpy(np.asarray(logits)))

    processor = ClapProcessor.from_pretrained(MODEL_ID, cache_dir=cache_dir)
    return pipeline(
        task="zero-shot-audio-classification", model=OnnxClapModel().eval(),
        tokenizer=processor.tokenizer, feature_extractor=processor.feature_extractor,
        device="cpu",
    )


def classify_clip(classifier, ffmpeg, path, duration, labels):
    import numpy as np

    candidates = list(dict.fromkeys([*labels.values(), *BACKGROUND_LABELS]))
    scores = {category: [] for category in labels}
    with TemporaryDirectory(prefix="fastvideoassembly-classify-") as directory:
        output = Path(directory) / "audio.f32"
        command = (FFmpeg(ffmpeg).option("v", "error").option("nostdin")
                   .input(path).output(str(output), t=duration, map="0:a:0", ac=1, ar=48000, f="f32le"))
        command.on("stderr", lambda line: print(line, file=sys.stderr, flush=True))
        command.execute()
        with output.open("rb") as decoded:
            while audio := decoded.read(WINDOW_SECONDS * 48000 * 4):
                results = classifier(np.frombuffer(audio, dtype=np.float32), candidate_labels=candidates)
                for category, label in labels.items():
                    scores[category].append(next(result["score"] for result in results if result["label"] == label))
    return {category: max(values) for category, values in scores.items()}


def main():
    request = json.load(sys.stdin)
    worker = local()
    initialization_lock = Lock()

    def classify(clip):
        for attempt in range(4):
            try:
                if not hasattr(worker, "classifier"):
                    # Transformers lazy imports and model setup must finish before another worker initializes.
                    with initialization_lock:
                        worker.classifier = create_classifier(
                            request["device"], request["precision"], request["gpu_index"], request["cache_dir"]
                        )
                score = classify_clip(worker.classifier, request["ffmpeg"], clip["path"],
                                      clip["duration"], request["labels"])
                return {"key": clip["key"], "path": clip["path"], "score": score}
            except Exception as error:
                memory_failure = (
                    isinstance(error, MemoryError)
                    or (isinstance(error, OSError) and (
                        error.errno == 12 or getattr(error, "winerror", None) in (8, 14, 1455)))
                    or any(message in (str(error) + str(getattr(error, "stderr", ""))).lower() for message in (
                        "out of memory", "not enough memory", "bad allocation", "bad_alloc",
                        "cannot allocate memory", "failed to allocate memory", "paging file is too small")))
                if not memory_failure or attempt == 3:
                    raise
                print(f"Memory exhaustion for {clip['path']}: {error}. "
                      f"Retry {attempt + 1}/3 in 5 seconds.", file=sys.stderr, flush=True)
            # Drop failed inference frames before waiting for memory to become available.
            gc.collect()
            sleep(5)

    with ThreadPoolExecutor(max_workers=request["threads"]) as executor:
        clips = iter(request["clips"])
        futures = {executor.submit(classify, clip) for clip in islice(clips, request["threads"])}
        while futures:
            completed, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                print(json.dumps(future.result()), flush=True)
            futures.update(executor.submit(classify, clip) for clip in islice(clips, len(completed)))


if __name__ == "__main__":
    main()
