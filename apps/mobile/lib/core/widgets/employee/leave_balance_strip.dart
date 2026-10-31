import 'package:flutter/material.dart';

import '../../theme/employee_tokens.dart';

/// One leave type's figures. [balance] and [reserved] are the API's decimal strings, shown
/// exactly as received (no re-formatting that could change precision).
class LeaveBalanceItem {
  const LeaveBalanceItem({required this.name, required this.balance, this.reserved});
  final String name;
  final String balance;
  final String? reserved;
}

/// Up to [maxItems] leave types (largest balance first) and an "All balances" link. Not cards:
/// a column per type. Scrolls horizontally when the columns do not fit.
class LeaveBalanceStrip extends StatelessWidget {
  const LeaveBalanceStrip({super.key, required this.items, this.maxItems = 3, this.onAll, this.flat = false});

  /// Home's layout: equal columns straight on the canvas (no card, no inline link; the section
  /// header carries "All balances"). Wraps instead of squeezing at large text or narrow widths.
  final bool flat;

  final List<LeaveBalanceItem> items;
  final int maxItems;
  final VoidCallback? onAll;

  static num _num(String s) => num.tryParse(s) ?? 0;
  static bool _hasReserved(String? r) => r != null && _num(r) != 0;

  @override
  Widget build(BuildContext context) {
    final t = EmployeeTokens.of(context);
    final theme = Theme.of(context);
    final shown = ([...items]..sort((a, b) => _num(b.balance).compareTo(_num(a.balance)))).take(maxItems).toList();
    final more = items.length - shown.length;
    if (flat) {
      Widget cell(LeaveBalanceItem item) => Semantics(
            container: true,
            label: '${item.name}: ${item.balance} days${_hasReserved(item.reserved) ? ', ${item.reserved} reserved' : ''}',
            excludeSemantics: true,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(item.name, style: theme.textTheme.bodyMedium?.copyWith(color: t.inkSecondary)),
                const SizedBox(height: 2),
                Text(item.balance, style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
                if (_hasReserved(item.reserved)) Text('${item.reserved} reserved', style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
              ],
            ),
          );
      final large = MediaQuery.textScalerOf(context).scale(16) / 16 >= 1.4;
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: LayoutBuilder(builder: (context, c) {
          if (large || c.maxWidth < 280) return Wrap(spacing: 24, runSpacing: 12, children: [for (final i in shown) cell(i)]);
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [for (final i in shown) Expanded(child: cell(i))]);
        }),
      );
    }
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16),
      padding: const EdgeInsets.fromLTRB(16, 12, 8, 4),
      decoration: BoxDecoration(
        color: t.sheet,
        borderRadius: BorderRadius.circular(EmployeeTokens.radiusSurface),
        border: Border.all(color: t.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final item in shown)
                  Padding(
                    padding: const EdgeInsets.only(right: 24),
                    child: Semantics(
                      container: true,
                      label: '${item.name}: ${item.balance} days${_hasReserved(item.reserved) ? ', ${item.reserved} reserved' : ''}',
                      excludeSemantics: true,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(item.name, style: theme.textTheme.bodySmall?.copyWith(color: t.inkSecondary)),
                          Text(item.balance, style: theme.textTheme.headlineSmall),
                          if (_hasReserved(item.reserved)) Text('${item.reserved} reserved', style: theme.textTheme.labelSmall?.copyWith(color: t.inkSecondary)),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(onPressed: onAll, child: Text(more > 0 ? 'All balances (+$more)' : 'All balances')),
          ),
        ],
      ),
    );
  }
}
