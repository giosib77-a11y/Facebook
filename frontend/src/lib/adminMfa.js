// ზუსტი ასლი backend-ის `admin._MFA_REQUIRED`-ისა — ერთად იცვლება.
export const ADMIN_MFA_REQUIRED = "ადმინ პანელისთვის საჭიროა ორფაქტორიანი შესვლა (MFA)";

// lib/api.js-ის 403 ობიექტი ({detail}) ან panel/api.js-ის Error (message).
export function isMfaRequired(err) {
  return err?.detail === ADMIN_MFA_REQUIRED || err?.message === ADMIN_MFA_REQUIRED;
}
