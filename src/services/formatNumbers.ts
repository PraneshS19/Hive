export const money = (n: number | null | undefined) => {
  if (n === null || n === undefined || isNaN(n)) return 'Unavailable';
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);
};
export const pct = (n: number | null | undefined) => {
  if (n === null || n === undefined || isNaN(n)) return '--';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
};
