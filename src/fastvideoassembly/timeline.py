"""Gap-free timeline layout and clip movement shared by buttons and dragging."""

from .assembly import clip_duration

TRACK_HEIGHT = 0.96
CLIP_HEIGHT = 0.5
CLIP_Y_OFFSET = -0.075


def clip_spans(track, config):
    start = 0.0
    for clip in track:
        end = start + clip_duration(clip, config)
        yield start, end, clip
        start = end


def move_clips(track, selected, target, config):
    """Return the new order and block start, measured after removing selected clips.

    Numeric targets are timeline seconds: insert at the first remaining boundary
    at or after the target, or append when the target is beyond the remaining end.
    """
    indices = [index for index, clip in enumerate(track) if clip in selected]
    if not indices:
        return track[:], None
    moved = [track[index] for index in indices]
    remaining = [clip for clip in track if clip not in selected]
    boundaries = [0.0] + [end for _start, end, _clip in clip_spans(remaining, config)]
    if target == "start":
        destination = 0
    elif target == "end":
        destination = len(remaining)
    elif target == "backward":
        destination = max(0, indices[0] - 1)
    elif target == "forward":
        destination = min(len(remaining), indices[-1] + 2 - len(moved))
    else:
        destination = 0
        while destination < len(remaining) and boundaries[destination] < target:
            destination += 1
    return remaining[:destination] + moved + remaining[destination:], boundaries[destination]
