from itertools import pairwise
from pathlib import Path

import pytest

from fastvideoassembly.assembly import Clip, RenderConfig, clip_duration
from fastvideoassembly.timeline import clip_spans, move_clips


@pytest.mark.parametrize("fps", ["24", "30", "30000/1001"])
@pytest.mark.parametrize("mask", range(1, 32))
def test_moves_preserve_membership_order_and_gap_free_duration(fps, mask):
    config = RenderConfig(fps=fps)
    track = [Clip(Path(f"{i}.mp4"), duration, 60, 120)
             for i, duration in enumerate([7.11, 0.101, 20.01, 2.1, 13.2])]
    original = track[:]
    selected = {clip for i, clip in enumerate(track) if mask & (1 << i)}
    moved = [clip for clip in track if clip in selected]
    remaining = [clip for clip in track if clip not in selected]
    total = sum(clip_duration(clip, config) for clip in track)
    remaining_end = sum(clip_duration(clip, config) for clip in remaining)
    targets = ["start", "end", "backward", "forward", 0.0, total, total + 5]
    for start, end, _clip in clip_spans(track, config):
        targets.extend([start, (start + end) / 2, end])
    for target in targets:
        result, position = move_clips(track, selected, target, config)
        assert track == original
        assert len(result) == len(track)
        assert set(result) == set(track)
        assert [clip for clip in result if clip not in selected] == remaining
        index = result.index(moved[0])
        assert result[index:index + len(moved)] == moved
        spans = list(clip_spans(result, config))
        assert spans[0][0] == 0
        assert spans[-1][1] == pytest.approx(total)
        assert all(left[1] == right[0] for left, right in pairwise(spans))
        assert spans[index][0] == pytest.approx(position)
        if isinstance(target, float):
            assert position >= min(target, remaining_end)
            if index:
                assert spans[index - 1][0] < target
        elif target == "start":
            assert index == 0
        elif target == "end":
            assert index == len(remaining)


def test_drop_time_is_measured_after_removing_selected_clips():
    track = [Clip(Path(f"{i}.mp4"), 10, 60, 120) for i in range(5)]
    result, position = move_clips(track, {track[0]}, 15.0, RenderConfig())
    assert result == [track[1], track[2], track[0], track[3], track[4]]
    assert position == 20
    result, position = move_clips(track, {track[0], track[2]}, 15.0, RenderConfig())
    assert result == [track[1], track[3], track[0], track[2], track[4]]
    assert position == 20


def test_drop_time_never_snaps_to_an_earlier_available_boundary():
    track = [Clip(Path(f"{i}.mp4"), 10, 60, 120) for i in range(4)]
    for target, expected in [(0.0, 0), (0.1, 10), (9.9, 10), (10.0, 10), (10.1, 20), (35.0, 30)]:
        _result, position = move_clips(track, {track[-1]}, target, RenderConfig())
        assert position == expected


@pytest.mark.parametrize("target", ["forward", "backward", "start", "end", 5.0])
def test_move_without_selected_members_is_unchanged(target):
    clip = Clip(Path("clip.mp4"), 1, 60, 120)
    assert move_clips([clip], set(), target, RenderConfig()) == ([clip], None)
    assert move_clips([], {clip}, target, RenderConfig()) == ([], None)
