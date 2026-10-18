from pathlib import Path
import runpy

import pytest


def compare(labels, predictions):
    function = runpy.run_path(str(Path(__file__).resolve().parents[4] / 'evaluation' / 'f_scores.py'))['compare']
    return function(labels, predictions)


def test_f1_f2_use_aligned_labels_and_penalize_missed_fraud():
    result = compare(dict(a=1, b=1, c=1, d=0, e=0), dict(a=True, b=False, c=False, d=True, e=False))
    assert (result['tp'], result['fp'], result['fn'], result['tn']) == (1, 1, 2, 1)
    assert result['f1'] == pytest.approx(2 / 5)
    assert result['f2'] == pytest.approx(5 / 14)
    assert result['label_prevalence'] == 3 / 5
    assert result['predicted_positive_rate'] == 2 / 5


def test_equal_predicted_fraud_rate_does_not_imply_correct_predictions():
    result = compare(dict(a=1, b=0), dict(a=False, b=True))
    assert result['label_prevalence'] == result['predicted_positive_rate'] == .5
    assert result['f1'] == result['f2'] == 0


def test_failed_inference_is_missing_coverage_and_not_a_negative_prediction():
    result = compare(dict(a=1, b=0), dict(a=None, b=False))
    assert result['coverage'] == .5 and result['missing'] == 1
    assert result['f1'] is None and result['f2'] is None
    assert result['fn'] == 0
    with pytest.raises(ValueError, match='align'):
        compare(dict(a=1), dict(b=True))
    with pytest.raises(ValueError):
        compare(dict(a=1), dict(a=.5))
