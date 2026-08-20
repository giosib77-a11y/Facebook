export const STATUS = {
  new: "ახალი",
  processing: "მუშავდება",
  done: "დასრულებული",
  cancelled: "გაუქმებული",
};

export const TIERS = [
  ["free", "უფასო"],
  ["basic", "საბაზისო"],
  ["standard", "სტანდარტი"],
  ["business", "ბიზნესი"],
];

export const tierLabel = (t) => {
  const f = TIERS.find((x) => x[0] === t);
  return f ? f[1] : t;
};
