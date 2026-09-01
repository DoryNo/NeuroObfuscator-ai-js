function calculatePrice(price, tier) {
  if (tier === "gold") {
    return price * 0.8;
  }
  return price;
}

function sumPositive(values) {
  let total = 0;
  for (const value of values) {
    if (value > 0) {
      total += value;
    }
  }
  return total;
}

function classify(value) {
  if (value < 0) {
    return "negative";
  }
  if (value === 0) {
    return "zero";
  }
  return "positive";
}
