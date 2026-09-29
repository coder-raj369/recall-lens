import pytest

from recall_lens.perception.detect import Region, iou, suppress


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (10, 10, 20, 20)) == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(50 / 150)


def test_suppress_keeps_best_of_overlapping_boxes_across_queries():
    regions = [
        Region((0, 0, 100, 50), "a barcode", 0.4),
        Region((2, 1, 101, 52), "a product label with printed text", 0.6),
        Region((200, 200, 300, 260), "a barcode", 0.3),
    ]
    kept = suppress(regions)
    assert [r.score for r in kept] == [0.6, 0.3]
