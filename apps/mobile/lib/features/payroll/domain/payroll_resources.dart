import 'package:flutter/material.dart';

import '../../../core/auth/permissions.dart';
import '../../../core/forms/form_spec.dart';
import '../../../core/format.dart';
import '../../../core/resource/resource_config.dart';
import '../presentation/bulk_assign_salary_dialog.dart';
import '../presentation/salary_structure_versions_section.dart';

/// Payroll configuration — salary components, salary structures and statutory rates. Each spec
/// mirrors a `*Create`/`*Update` schema in `apps/api/.../payroll/schemas.py` and the web form.

const _active = FieldSpec('is_active', 'Active', kind: FieldKind.toggle, editOnly: true);

// ---- salary components ------------------------------------------------------------------------

const componentTypeLabels = {'EARNING': 'Earning', 'DEDUCTION': 'Deduction', 'EMPLOYER_CONTRIBUTION': 'Employer contribution'};

const salaryComponentSpec = FormSpec(name: 'salary_component', label: 'Salary component', defaults: {
  'component_type': 'EARNING',
  'is_taxable': true,
  'is_prorated': true,
  'show_on_payslip': true,
  'display_order': 0,
}, fields: [
  FieldSpec('code', 'Code', kind: FieldKind.upper, required: true, readOnlyOnEdit: true, hint: 'Capital letters, digits and underscores, e.g. BASIC'),
  FieldSpec('name', 'Name', required: true),
  FieldSpec('component_type', 'Type', kind: FieldKind.select, required: true, options: ['EARNING', 'DEDUCTION', 'EMPLOYER_CONTRIBUTION'], optionLabels: componentTypeLabels),
  FieldSpec('is_taxable', 'Taxable', kind: FieldKind.toggle),
  FieldSpec('is_pf_wage', 'Counts toward the PF wage', kind: FieldKind.toggle),
  FieldSpec('is_esi_wage', 'Counts toward the ESI wage', kind: FieldKind.toggle),
  FieldSpec('is_prorated', 'Prorated by paid days', kind: FieldKind.toggle),
  FieldSpec('show_on_payslip', 'Show on the payslip', kind: FieldKind.toggle),
  FieldSpec('display_order', 'Display order', kind: FieldKind.integer),
  _active,
]);

final salaryComponentResource = ResourceConfig(
  title: 'Salary Components',
  singular: 'Salary component',
  path: '/payroll/salary-components',
  spec: salaryComponentSpec,
  rowTitle: (r) => '${r['name']} (${r['code']})',
  rowSubtitle: (r) => '${componentTypeLabels[r['component_type']] ?? r['component_type']}${r['is_system'] == true ? ' · system' : ''}',
  manage: payrollSetupManage,
);

// ---- salary structures ------------------------------------------------------------------------

const salaryStructureSpec = FormSpec(name: 'salary_structure', label: 'Salary structure', fields: [
  FieldSpec('code', 'Code', kind: FieldKind.upper, required: true, readOnlyOnEdit: true, hint: 'Capital letters, digits and underscores'),
  FieldSpec('name', 'Name', required: true),
  FieldSpec('description', 'Description', kind: FieldKind.multiline),
  _active,
]);

/// Per-type rules a field spec can't express (mirror the web structure editor): a fixed line needs
/// an amount, a percentage line needs a percentage, and a "% of component" line needs the base.
Map<String, String> _validateLine(Map<String, dynamic> v) {
  String text(String k) => ((v[k] ?? '') as String).trim();
  final errors = <String, String>{};
  switch (text('calculation_type')) {
    case 'FIXED':
      if (text('amount_monthly_minor').isEmpty) errors['amount_monthly_minor'] = 'Enter the monthly amount.';
    case 'PERCENTAGE_OF_CTC' || 'PERCENTAGE_OF_GROSS':
      if (text('percentage').isEmpty) errors['percentage'] = 'Enter a percentage.';
    case 'PERCENTAGE_OF_COMPONENT':
      if (text('percentage').isEmpty) errors['percentage'] = 'Enter a percentage.';
      if (text('base_salary_component_id').isEmpty) errors['base_salary_component_id'] = 'Choose the component it is a percentage of.';
  }
  final pct = num.tryParse(text('percentage'));
  if (pct != null && (pct < 0 || pct > 100)) errors['percentage'] = 'A percentage is between 0 and 100.';
  return errors;
}

const calculationTypeLabels = {
  'FIXED': 'Fixed amount',
  'PERCENTAGE_OF_CTC': '% of monthly CTC',
  'PERCENTAGE_OF_GROSS': '% of gross',
  'PERCENTAGE_OF_COMPONENT': '% of another component',
  'BALANCING': 'Balance of gross',
};

const appliesWhenLabels = {'ALWAYS': 'Always', 'PF_APPLICABLE': 'Only if PF applies', 'ESI_APPLICABLE': 'Only if ESI applies'};

/// The fields of a `SalaryStructureLineInput`; the contract test checks them against the API.
const structureLineSpec = FormSpec(name: 'structure_line', label: 'Line', defaults: {'applies_when': 'ALWAYS'}, extraValidate: _validateLine, fields: [
  FieldSpec('salary_component_id', 'Component', kind: FieldKind.choice, choiceKey: 'salary_components', required: true),
  FieldSpec('calculation_type', 'Calculation', kind: FieldKind.select, required: true, options: ['FIXED', 'PERCENTAGE_OF_CTC', 'PERCENTAGE_OF_GROSS', 'PERCENTAGE_OF_COMPONENT', 'BALANCING'], optionLabels: calculationTypeLabels),
  FieldSpec('amount_monthly_minor', 'Monthly amount (₹)', kind: FieldKind.money, hint: 'For a fixed amount'),
  FieldSpec('percentage', 'Percentage', kind: FieldKind.decimal, hint: 'For a percentage line, 0–100'),
  FieldSpec('base_salary_component_id', 'Percentage of', kind: FieldKind.choice, choiceKey: 'salary_components', hint: 'For "% of another component"'),
  FieldSpec('max_monthly_minor', 'Monthly cap (₹)', kind: FieldKind.money),
  FieldSpec('applies_when', 'Applies', kind: FieldKind.select, required: true, options: ['ALWAYS', 'PF_APPLICABLE', 'ESI_APPLICABLE'], optionLabels: appliesWhenLabels),
]);

final salaryStructureResource = ResourceConfig(
  title: 'Salary Structures',
  singular: 'Salary structure',
  path: '/payroll/salary-structures',
  spec: salaryStructureSpec,
  rowTitle: (r) => '${r['name']} (${r['code']})',
  rowSubtitle: (r) => r['description'] as String?,
  manage: payrollSetupManage,
  detailExtras: (context, row, reload) => SalaryStructureVersionsSection(structure: row, onChanged: reload),
  listActions: (context, rows, reload) => [
    IconButton(
      tooltip: 'Assign to employees',
      icon: const Icon(Icons.group_add_outlined),
      onPressed: () => showBulkAssignSalaryDialog(context, [for (final s in rows) if (hasCurrentVersion(s)) s]),
    ),
  ],
);

/// A structure employees can be assigned to: active, with a published, open-ended version.
bool hasCurrentVersion(Map<String, dynamic> s) =>
    s['is_active'] != false && ((s['versions'] as List?) ?? const []).any((v) => v is Map && v['status'] == 'PUBLISHED' && v['effective_to'] == null);

/// One line of a structure as text (mirrors `describeLine` in web's salary-structures/[id]/page.tsx).
String describeStructureLine(Map<String, dynamic> line, List<Map<String, dynamic>> allLines) {
  String baseName() {
    final id = line['base_salary_component_id'];
    for (final l in allLines) {
      if (l['salary_component_id'] == id) return l['component_name'] as String;
    }
    return 'another component';
  }

  var text = switch (line['calculation_type']) {
    'FIXED' => formatInr((line['amount_monthly_minor'] as num?) ?? 0),
    'PERCENTAGE_OF_CTC' => '${line['percentage']}% of monthly CTC',
    'PERCENTAGE_OF_GROSS' => '${line['percentage']}% of gross',
    'PERCENTAGE_OF_COMPONENT' => '${line['percentage']}% of ${baseName()}',
    'BALANCING' => 'Balance of gross',
    final other => '$other',
  };
  if (line['max_monthly_minor'] != null) text += ', at most ${formatInr(line['max_monthly_minor'] as num)}';
  final applies = line['applies_when'];
  if (applies != null && applies != 'ALWAYS') text += ' (${(appliesWhenLabels[applies] ?? '$applies').toLowerCase()})';
  return text;
}

// ---- statutory rates --------------------------------------------------------------------------

const statutorySchemeLabels = {
  'PF': 'Provident Fund',
  'ESI': "Employees' State Insurance",
  'PT': 'Professional tax',
  'LWF': 'Labour welfare fund',
  'TDS': 'Income tax (TDS)',
};

/// Schemes whose rate is per state (the backend requires a state for these, and forbids one for the rest).
const stateSchemes = {'PT', 'LWF'};

const _pctHint = '0–100';

const pfParametersSpec = FormSpec(name: 'pf', label: 'Provident Fund', fields: [
  FieldSpec('employee_percent', 'Employee %', kind: FieldKind.decimal, required: true, hint: _pctHint),
  FieldSpec('employer_percent', 'Employer %', kind: FieldKind.decimal, required: true, hint: _pctHint),
  FieldSpec('eps_percent', 'EPS % (part of employer)', kind: FieldKind.decimal, required: true, hint: _pctHint),
  FieldSpec('edli_percent', 'EDLI %', kind: FieldKind.decimal, required: true, hint: _pctHint),
  FieldSpec('admin_percent', 'Admin %', kind: FieldKind.decimal, required: true, hint: _pctHint),
  FieldSpec('wage_ceiling_minor', 'Wage ceiling (₹)', kind: FieldKind.money, required: true),
  FieldSpec('eps_age_limit', 'EPS age limit', kind: FieldKind.integer, required: true),
]);

const esiParametersSpec = FormSpec(name: 'esi', label: "Employees' State Insurance", fields: [
  FieldSpec('employee_percent', 'Employee %', kind: FieldKind.decimal, required: true, hint: _pctHint),
  FieldSpec('employer_percent', 'Employer %', kind: FieldKind.decimal, required: true, hint: _pctHint),
  FieldSpec('wage_ceiling_minor', 'Wage ceiling (₹)', kind: FieldKind.money, required: true),
  FieldSpec('employee_exempt_daily_wage_minor', 'Exempt daily wage (₹)', kind: FieldKind.money, required: true),
]);

const ptParametersSpec = FormSpec(name: 'pt', label: 'Professional tax', fields: [
  FieldSpec('slabs', 'Slabs (none = the state levies no professional tax)', kind: FieldKind.rows, rowNoun: 'slab', rowSpec: FormSpec(name: 'pt_slab', label: 'Slab', fields: [
    FieldSpec('min_minor', 'From (₹)', kind: FieldKind.money, required: true),
    FieldSpec('max_minor', 'To (₹)', kind: FieldKind.money),
    FieldSpec('amount_minor', 'Monthly amount (₹)', kind: FieldKind.money, required: true),
    FieldSpec('gender', 'Gender', kind: FieldKind.select, options: ['MALE', 'FEMALE']),
    FieldSpec('month_amounts', 'Month amounts', kind: FieldKind.hidden),
  ])),
]);

const lwfParametersSpec = FormSpec(name: 'lwf', label: 'Labour welfare fund', fields: [
  FieldSpec('months', 'Deducted in months', kind: FieldKind.multiChoice, choiceKey: 'months', required: true, intValue: true),
  FieldSpec('slabs', 'Slabs', kind: FieldKind.rows, required: true, rowNoun: 'slab', rowSpec: FormSpec(name: 'lwf_slab', label: 'Slab', fields: [
    FieldSpec('min_minor', 'From (₹)', kind: FieldKind.money, required: true),
    FieldSpec('max_minor', 'To (₹)', kind: FieldKind.money),
    FieldSpec('employee_minor', 'Employee (₹)', kind: FieldKind.money, required: true),
    FieldSpec('employer_minor', 'Employer (₹)', kind: FieldKind.money, required: true),
  ])),
]);

const tdsParametersSpec = FormSpec(name: 'tds', label: 'Income tax (TDS)', defaults: {'regime': 'NEW'}, fields: [
  FieldSpec('regime', 'Regime', kind: FieldKind.select, required: true, options: ['NEW']),
  FieldSpec('standard_deduction_minor', 'Standard deduction (₹)', kind: FieldKind.money, required: true),
  FieldSpec('rebate_taxable_income_limit_minor', 'Rebate limit — taxable income (₹)', kind: FieldKind.money, required: true),
  FieldSpec('cess_percent', 'Cess %', kind: FieldKind.decimal, required: true, hint: _pctHint),
  FieldSpec('surcharge_warning_income_minor', 'Surcharge warning above (₹)', kind: FieldKind.money, required: true),
  FieldSpec('slabs', 'Tax slabs', kind: FieldKind.rows, required: true, rowNoun: 'slab', rowSpec: FormSpec(name: 'tds_slab', label: 'Slab', fields: [
    FieldSpec('min_minor', 'From (₹)', kind: FieldKind.money, required: true),
    FieldSpec('max_minor', 'To (₹)', kind: FieldKind.money),
    FieldSpec('percent', 'Rate %', kind: FieldKind.decimal, required: true, hint: _pctHint),
  ])),
]);

const statutoryParameterSpecs = {
  'PF': pfParametersSpec,
  'ESI': esiParametersSpec,
  'PT': ptParametersSpec,
  'LWF': lwfParametersSpec,
  'TDS': tdsParametersSpec,
};

/// One-line summary of a rate's figures for the list (mirrors the web `summariseStatutoryRate`).
String summariseStatutoryRate(Map<String, dynamic> rate) {
  final p = (rate['parameters'] as Map?)?.cast<String, dynamic>() ?? const {};
  switch (rate['scheme']) {
    case 'PF':
      return 'Employee ${p['employee_percent']}% · employer ${p['employer_percent']}% (EPS ${p['eps_percent']}%) · ceiling ${formatInr(num.tryParse('${p['wage_ceiling_minor']}') ?? 0)}';
    case 'ESI':
      return 'Employee ${p['employee_percent']}% · employer ${p['employer_percent']}% · ceiling ${formatInr(num.tryParse('${p['wage_ceiling_minor']}') ?? 0)}';
    case 'PT':
      final slabs = (p['slabs'] as List?) ?? const [];
      return slabs.isEmpty ? 'No professional tax in this state' : '${slabs.length} slab(s)';
    case 'LWF':
      return 'Deducted in month(s) ${((p['months'] as List?) ?? const []).join(', ')}';
    case 'TDS':
      final slabs = (p['slabs'] as List?) ?? const [];
      final top = slabs.isEmpty ? '0' : '${(slabs.last as Map)['percent']}';
      return '${p['regime'] ?? 'NEW'} regime · standard deduction ${formatInr(num.tryParse('${p['standard_deduction_minor']}') ?? 0)} · up to $top%';
  }
  return '';
}
