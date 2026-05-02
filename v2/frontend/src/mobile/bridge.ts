import type { Role } from '../auth/rbac';
import type { DangerousControlId, DangerousControlLevel } from '../constants/dangerousControls';

export interface MobileNavigationBridge {
  navigateTo(path: string): void;
  goBack(): void;
  currentPath(): string;
}

export interface MobileRbacBridge {
  getActorRole(): Role;
  refreshSession(): Promise<Role>;
}

export interface MobilePushNotificationBridge {
  registerForApprovalRequests(): Promise<void>;
  unregister(): Promise<void>;
  isRegistered(): Promise<boolean>;
}

export interface MobileApprovalRequestPayload {
  controlId: DangerousControlId;
  requiredLevel: DangerousControlLevel;
  contextHash: string;
}

export interface MobileApprovalBridge {
  requestApproval(payload: MobileApprovalRequestPayload): Promise<{ requestId: string }>;
  fetchApprovalStatus(requestId: string): Promise<'pending' | 'approved' | 'denied' | 'expired'>;
}

export interface MobileBridge {
  navigation: MobileNavigationBridge;
  rbac: MobileRbacBridge;
  push: MobilePushNotificationBridge;
  approvals: MobileApprovalBridge;
}

export const MOBILE_BRIDGE_DISABLED_REASON =
  'Mobile bridge contract is TypeScript-only in milestone E. Push notifications and ' +
  'concrete bridge implementations are deferred per 16_MOBILE_IPHONE_AND_PWA_READINESS.md.';

export const MOBILE_BRIDGE_FEATURES = {
  pushNotificationsEnabled: false,
  reactNativeBridgeShipped: false,
  swiftUiBridgeShipped: false,
} as const;
