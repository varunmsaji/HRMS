/// The API serialises `Decimal` fields (leave balances, day counts, percentages) as JSON
/// *strings* (`"12.50"`), while integer minor-unit fields stay numbers. Read decimals through
/// these instead of `as num`, which throws on the string form.
num parseNum(dynamic value) => value is num ? value : num.parse(value.toString());

num? parseNumOrNull(dynamic value) => value == null ? null : parseNum(value);
