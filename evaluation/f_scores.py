"""Offline F1/F2 comparison; inputs must share frozen dataset/row identities.

This module neither reads credentials nor calls a model. Historical AP benchmark
protocols remain frozen; use this report for the new F1/F2 comparison.
"""


def compare(labels, predictions):
    if not labels or labels.keys() != predictions.keys():
        raise ValueError('Labels and predictions must align on identical nonempty row identities.')
    if any(type(value) not in {int, bool} or value not in (0, 1) for value in labels.values()):
        raise ValueError('Labels must be binary.')
    if any(value is not None and type(value) is not bool for value in predictions.values()):
        raise ValueError('Predictions must be binary decisions or missing, not probabilities.')
    tp = fp = fn = tn = missing = 0
    for key, label in labels.items():
        decision = predictions[key]
        if decision is None:
            missing += 1
        elif decision and label:
            tp += 1
        elif decision:
            fp += 1
        elif label:
            fn += 1
        else:
            tn += 1
    complete = missing == 0
    scored = len(labels) - missing
    return {
        'rows': len(labels), 'successful': scored, 'missing': missing,
        'coverage': scored / len(labels), 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
        'f1': 2 * tp / (2 * tp + fp + fn) if complete and tp else (0.0 if complete else None),
        'f2': 5 * tp / (5 * tp + fp + 4 * fn) if complete and tp else (0.0 if complete else None),
        'label_prevalence': sum(labels.values()) / len(labels),
        'predicted_positive_rate': (tp + fp) / scored if scored else None,
    }
