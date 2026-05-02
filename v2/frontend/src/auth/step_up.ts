export type StepUpRequirement = {
  required: boolean;
  reason: string;
  approval_scope?: string;
};

export function requiresStepUpAuth(scope: string): StepUpRequirement {
  const sensitiveScopes = new Set([
    "write:approval",
    "write:kill_switch",
    "write:live_gate",
    "write:strategy",
    "write:trader_fleet",
  ]);

  const required = sensitiveScopes.has(scope);
  return {
    required,
    reason: required
      ? "Sensitive admin action requires step-up approval."
      : "Step-up approval not required for this scope.",
    approval_scope: scope,
  };
}
