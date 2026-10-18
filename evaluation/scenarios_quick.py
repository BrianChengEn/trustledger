"""Independent scenario expectations for the quick evaluation.

Expectations are literals checked against the documented product rules in
docs/00-overall-architecture-report.md section 7. They are not produced by
calling backend.app.core.rules.analyze, and they are not human-verified
ground truth.

Documented sentences:
- duplicate candidate: 同一使用者、同類別、同金額、24 小時內至少 2 筆。
- high amount: 金額大於合成使用者過去 30 天同類別中位數的 3 倍，且至少大於 USD 100。
- subscription change: 相同訂閱類別相較上次增加超過 20%。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.core.rules import analyze
from app.schemas.transaction import Transaction

T0 = datetime(2026, 4, 1, 12, tzinfo=timezone.utc)


def tx(name: str, hours: float, amount: float, category: str, merchant: str,
       *, subscription: bool = False, account: str = "acct_scenario_a",
       direction: str = "debit") -> Transaction:
    return Transaction(
        id=name,
        occurred_at=T0 + timedelta(hours=hours),
        amount=amount,
        currency="USD",
        direction=direction,
        merchant_display=merchant,
        merchant_category=category,
        source="synthetic",
        account_token=account,
        is_subscription=subscription,
    )


@dataclass
class Scenario:
    case_id: str
    narrative: str
    why_expected: str
    expected_alert: str
    expected_needs_human: bool
    current: Transaction
    history: list[Transaction] = field(default_factory=list)
    prior_confirmation: str = "unknown"


def documented_alert(current: Transaction, history: list[Transaction]) -> str:
    """Oracle for the written product rules. Not the production function."""
    if current.direction != "debit":
        return "none"
    prior = [
        item for item in history
        if item.account_token == current.account_token and item.id != current.id
        and item.occurred_at <= current.occurred_at and item.direction == "debit"
    ]
    duplicate = any(
        item.merchant_category == current.merchant_category and item.amount == current.amount
        and 0 <= (current.occurred_at - item.occurred_at).total_seconds() <= 86400
        for item in prior
    )
    if duplicate:
        return "duplicate"
    window = [
        item.amount for item in prior
        if item.merchant_category == current.merchant_category
        and 0 < (current.occurred_at - item.occurred_at).total_seconds() <= 30 * 86400
    ]
    if window:
        median = statistics.median(window)
        if current.amount > 100 and current.amount > 3 * median:
            return "amount_anomaly"
    subscriptions = [
        item for item in prior
        if item.is_subscription and current.is_subscription
        and item.merchant_category == current.merchant_category and item.amount > 0
    ]
    if subscriptions:
        previous = max(subscriptions, key=lambda item: item.occurred_at)
        if (current.amount - previous.amount) / previous.amount > 0.2:
            return "subscription_change"
    return "none"


def build_scenarios() -> list[Scenario]:
    steady = [tx(f"hist_{index}", -24 * (index + 2), amount, "electronics", "Harbor")
              for index, amount in enumerate([270, 280, 290, 280, 275, 285, 280, 280])]
    small = [tx(f"small_{index}", -24 * (index + 2), 40, "dining", "Cafe") for index in range(4)]
    return [
        Scenario("dup_same_merchant_2h", "Second identical merchant charge two hours later.",
                 "Same user, category, and amount inside 24 hours.", "duplicate", True,
                 tx("cur", 2, 15, "dining", "Cafe"), [tx("old", 0, 15, "dining", "Cafe")]),
        Scenario("dup_same_category_other_merchant", "Same category and amount, different merchant.",
                 "The written rule keys on category, not merchant name.", "duplicate", True,
                 tx("cur", 2, 15, "dining", "Other Cafe"), [tx("old", 0, 15, "dining", "Cafe")]),
        Scenario("dup_same_merchant_25h", "Same charge 25 hours later.",
                 "Outside the 24 hour window.", "none", False,
                 tx("cur", 25, 15, "dining", "Cafe"), [tx("old", 0, 15, "dining", "Cafe")]),
        Scenario("dup_exactly_24h", "Same charge exactly 24 hours later.",
                 "24 hours is still inside the written window.", "duplicate", True,
                 tx("cur", 24, 15, "dining", "Cafe"), [tx("old", 0, 15, "dining", "Cafe")]),
        Scenario("dup_just_over_24h", "Same charge one second past 24 hours.",
                 "The written window stops at 24 hours.", "none", False,
                 tx("cur", 24 + 1 / 3600, 15, "dining", "Cafe"), [tx("old", 0, 15, "dining", "Cafe")]),
        Scenario("dup_different_amount", "Same merchant two hours later, different amount.",
                 "Amount differs, so it is not a duplicate candidate.", "none", False,
                 tx("cur", 2, 16, "dining", "Cafe"), [tx("old", 0, 15, "dining", "Cafe")]),
        Scenario("dup_different_category_same_merchant", "Same merchant and amount, different category.",
                 "The written duplicate rule requires the same category.", "none", False,
                 tx("cur", 2, 15, "groceries", "Cafe"), [tx("old", 0, 15, "dining", "Cafe")]),
        Scenario("dup_other_customer", "Another customer has the same merchant and amount.",
                 "Duplicate history is per user.", "none", False,
                 tx("cur", 2, 15, "dining", "Cafe", account="acct_scenario_b"),
                 [tx("old", 0, 15, "dining", "Cafe", account="acct_scenario_a")]),
        Scenario("dup_credit", "A credit with the same merchant and amount.",
                 "The written charge rules are applied to debits in this suite.", "none", False,
                 tx("cur", 2, 15, "dining", "Cafe", direction="credit"),
                 [tx("old", 0, 15, "dining", "Cafe")]),
        Scenario("repeat_other_category_and_merchant", "Same amount in another category and merchant.",
                 "Category and merchant both differ.", "none", False,
                 tx("cur", 2, 15, "transportation", "Metro"), [tx("old", 0, 15, "dining", "Cafe")]),
        Scenario("amt_90_no_history", "Ninety dollars with no history.",
                 "Below USD 100 and there is no median.", "none", False, tx("cur", 0, 90, "electronics", "Harbor")),
        Scenario("amt_100_no_history", "Exactly USD 100 with no history.",
                 "The written rule requires an amount greater than USD 100.", "none", False,
                 tx("cur", 0, 100, "electronics", "Harbor")),
        Scenario("amt_249_no_history", "USD 249 with no personal baseline.",
                 "No median, so the written high-amount rule does not fire.", "none", False,
                 tx("cur", 0, 249, "electronics", "Harbor")),
        Scenario("amt_250_no_history", "USD 250 with no personal baseline.",
                 "No median, so the written high-amount rule does not fire.", "none", False,
                 tx("cur", 0, 250, "electronics", "Harbor")),
        Scenario("amt_251_no_history", "USD 251 with no personal baseline.",
                 "No median, so the written high-amount rule does not fire.", "none", False,
                 tx("cur", 0, 251, "electronics", "Harbor")),
        Scenario("amt_849_no_history", "USD 849 with no personal baseline.",
                 "A large first purchase still has no 30 day median.", "none", False,
                 tx("cur", 0, 849, "electronics", "Harbor")),
        Scenario("amt_high_but_consistent", "USD 288 after a month of similar electronics spend.",
                 "288 is not more than three times the category median.", "none", False,
                 tx("cur", 0, 288, "electronics", "Harbor"), steady),
        Scenario("amt_above_median_below_250", "USD 180 after repeated USD 40 dining.",
                 "180 is above USD 100 and above three times the median, but below 250.", "amount_anomaly", True,
                 tx("cur", 0, 180, "dining", "Cafe"), small),
        Scenario("amt_above_median_and_250", "USD 300 after repeated USD 40 dining.",
                 "300 clears both the written median test and USD 100.", "amount_anomaly", True,
                 tx("cur", 0, 300, "dining", "Cafe"), small),
        Scenario("amt_equal_three_times_median", "USD 120 after repeated USD 40 dining.",
                 "Equal to three times the median is not greater than three times.", "none", False,
                 tx("cur", 0, 120, "dining", "Cafe"), small),
        Scenario("sub_up_25_same_merchant", "Recurring charge rises from 20 to 25.",
                 "Same subscription category increased by more than 20 percent.", "subscription_change", True,
                 tx("cur", 240, 25, "streaming", "Stream", subscription=True),
                 [tx("old", 0, 20, "streaming", "Stream", subscription=True)]),
        Scenario("sub_up_10_same_merchant", "Recurring charge rises from 20 to 22.",
                 "Ten percent is not more than 20 percent.", "none", False,
                 tx("cur", 240, 22, "streaming", "Stream", subscription=True),
                 [tx("old", 0, 20, "streaming", "Stream", subscription=True)]),
        Scenario("sub_up_exactly_20", "Recurring charge rises from 25 to 30.",
                 "Exactly 20 percent is not more than 20 percent.", "none", False,
                 tx("cur", 240, 30, "streaming", "Stream", subscription=True),
                 [tx("old", 0, 25, "streaming", "Stream", subscription=True)]),
        Scenario("sub_up_25_other_merchant", "Same category subscription rises at a different merchant.",
                 "The written rule says the same subscription category, not the same merchant.",
                 "subscription_change", True,
                 tx("cur", 240, 25, "streaming", "Other Stream", subscription=True),
                 [tx("old", 0, 20, "streaming", "Stream", subscription=True)]),
        Scenario("sub_legitimate_upgrade_25", "A described plan upgrade from 20 to 25.",
                 "A legitimate upgrade is still a reviewable increase over 20 percent.",
                 "subscription_change", True,
                 tx("cur", 240, 25, "fitness_subscription", "Fit", subscription=True),
                 [tx("old", 0, 20, "fitness_subscription", "Fit", subscription=True)]),
        Scenario("sub_decrease", "Recurring charge falls from 40 to 30.",
                 "A decrease is not an increase over 20 percent.", "none", False,
                 tx("cur", 240, 30, "streaming", "Stream", subscription=True),
                 [tx("old", 0, 40, "streaming", "Stream", subscription=True)]),
        Scenario("confirmed_duplicate_stays_human", "Confirmed dining, then a real duplicate.",
                 "A prior normal confirmation does not clear a new rule match.", "duplicate", True,
                 tx("cur", 2, 15, "dining", "Cafe"), [tx("old", 0, 15, "dining", "Cafe")],
                 prior_confirmation="normal"),
        Scenario("confirmed_new_high_amount", "Confirmed dining, then USD 300 against a USD 40 baseline.",
                 "The new amount still matches the written high-amount rule.", "amount_anomaly", True,
                 tx("cur", 0, 300, "dining", "Cafe"), small, prior_confirmation="normal"),
        Scenario("confirmed_other_merchant_repeat", "Confirmed dining, then the same amount at a new merchant.",
                 "Written duplicate rule still matches on category and amount.", "duplicate", True,
                 tx("cur", 2, 15, "dining", "Other Cafe"), [tx("old", 0, 15, "dining", "Cafe")],
                 prior_confirmation="normal"),
        Scenario("confirmed_ordinary_purchase", "Confirmed dining, then one ordinary new purchase.",
                 "No written rule matches, so confirmation alone creates no alert.", "none", False,
                 tx("cur", 0, 12, "dining", "Cafe"), prior_confirmation="normal"),
    ]


def run_scenarios() -> list[dict]:
    results = []
    for scenario in build_scenarios():
        doc = documented_alert(scenario.current, scenario.history)
        if doc != scenario.expected_alert:
            raise RuntimeError(
                f"{scenario.case_id}: handwritten expectation {scenario.expected_alert} "
                f"disagrees with the documented oracle {doc}"
            )
        actual = analyze(
            scenario.current, scenario.history, scenario.case_id, scenario.prior_confirmation,
        )
        passed = actual.alert_type == scenario.expected_alert and actual.needs_human == scenario.expected_needs_human
        reason = ""
        if not passed:
            reason = (
                f"Expected {scenario.expected_alert} (needs_human={scenario.expected_needs_human}); "
                f"production returned {actual.alert_type} (needs_human={actual.needs_human}). "
                f"{scenario.why_expected}"
            )
        results.append({
            "case_id": scenario.case_id,
            "narrative": scenario.narrative,
            "why_expected": scenario.why_expected,
            "expected_alert": scenario.expected_alert,
            "actual_alert": actual.alert_type,
            "expected_needs_human": scenario.expected_needs_human,
            "actual_needs_human": actual.needs_human,
            "pass": passed,
            "mismatch_reason": reason,
            "label_type": "independent scenario expectation, not human-verified ground truth",
        })
    return results
