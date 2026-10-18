// A-002: რედაქტირებისას PUT-ში მხოლოდ შეცვლილი ველები იგზავნება, რომ ძველი snapshot-ის
// მარაგი (quantity) სერვერზე შეკვეთებით შეცვლილ მარაგს არ გადააწეროს (lost update).

const FIELDS = ["name", "price", "quantity", "sku", "description", "is_active", "image_url"];

/** არსებული პროდუქტი → იგივე ნორმალიზებული ფორმა, რასაც ფორმის payload იყენებს */
export function normalizeProduct(p) {
  return {
    name: (p.name || "").trim(),
    price: Number(p.price) || 0,
    quantity: Number(p.quantity) || 0,
    sku: (p.sku || "").trim() || null,
    description: (p.description || "").trim() || null,
    is_active: !!p.is_active,
    image_url: p.image_url || null,
  };
}

/** აბრუნებს მხოლოდ იმ ველებს, რომლებიც payload-ში snapshot-ისგან განსხვავდება ({} თუ არაფერი შეცვლილა) */
export function changedProductFields(snapshot, payload) {
  const before = normalizeProduct(snapshot);
  const diff = {};
  for (const k of FIELDS) {
    if (payload[k] !== before[k]) diff[k] = payload[k];
  }
  return diff;
}
