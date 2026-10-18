import raw from './examples.json';
import type {
  Alert, Analysis, Confirmation, Explanation, Memory, PrivacyPreview, Transaction,
} from '../api';

/** UI fixtures. They match the FastAPI models and are not live provider calls. */
export const fixtureMeta = {
  synthetic: true as const,
  liveProviderVerified: false as const,
  disclaimer: raw.disclaimer,
};

export const baselineTransactions = raw.baseline_transactions as Transaction[];
export const transactionDetail = raw.transaction_detail as Transaction;
export const devLibraryTransactions = raw.dev_library_transactions as Transaction[];
export const rulesOnlyAnalysis = raw.analyses.rules_only as Analysis;
export const jevShapeAnalysis = raw.analyses.jev_shape as Analysis;
export const duplicateAlert = raw.alerts.duplicate_open as Alert;
export const amountAlert = raw.alerts.amount_open as Alert;
export const subscriptionAlert = raw.alerts.subscription_open as Alert;
export const confirmedNormalAlert = raw.alerts.confirmed_normal as Alert;
export const templateExplanation = raw.explanations.template_shape as Explanation;
export const fallbackExplanation = raw.explanations.fallback_shape as Explanation;
export const geminiShapeExplanation = raw.explanations.gemini_shape as Explanation;
export const confirmation = raw.confirmation as Confirmation;
export const memoryConsent = raw.memory as Memory;
export const privacyPreview = raw.privacy_preview as PrivacyPreview;
export const apiError = raw.error;
export const emptyTransactions = raw.empty_transactions as Transaction[];
export const loadingState = raw.loading;
