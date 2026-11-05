import '../../../core/forms/form_spec.dart';

/// A starting point offered when creating a policy or shift. [values] are wire values layered over
/// the config's [PolicySetupConfig.base].
class SetupTemplate {
  const SetupTemplate({required this.key, required this.label, required this.description, required this.defaultName, this.values = const {}});
  final String key;
  final String label;
  final String description;
  final String defaultName;
  final Map<String, dynamic> values;
}

/// Everything that differs between the things created on one page: attendance, overtime,
/// regularization and leave policies, and shifts. The screen reads this and calls `$path/setup`,
/// which creates the record, fills its rules and (optionally) publishes and assigns it in one step.
class PolicySetupConfig {
  const PolicySetupConfig({
    required this.title,
    required this.path,
    required this.rules,
    required this.everydayKeys,
    required this.base,
    required this.templates,
    this.policyKind,
    this.leaveTyped = false,
    this.requiredToPublish = const {},
  });

  final String title;

  /// List endpoint; `$path/setup` is the one-step create.
  final String path;

  /// The rules form, without the start date (that is asked for when publishing).
  final FormSpec rules;

  /// Fields shown up front, in this order. The rest of [rules] sits under "Advanced settings".
  final List<String> everydayKeys;

  /// Wire values every template starts from (the server's own defaults).
  final Map<String, dynamic> base;
  final List<SetupTemplate> templates;

  /// The assignable policy kind, or null for things that are not assigned (shifts).
  final String? policyKind;

  /// Each record covers one leave type, chosen at creation.
  final bool leaveTyped;

  /// Rule keys that need a value before the record can be published, with the message to show.
  final Map<String, String> requiredToPublish;
}

/// [f] with a different condition and/or required flag. FieldSpec is const and has no copy method.
FieldSpec adjusted(FieldSpec f, {String? showWhen, bool? required}) => FieldSpec(
      f.key,
      f.label,
      kind: f.kind,
      required: required ?? f.required,
      options: f.options,
      optionLabels: f.optionLabels,
      choiceKey: f.choiceKey,
      showWhen: showWhen ?? f.showWhen,
      hint: f.hint,
      exactLength: f.exactLength,
      readOnlyOnEdit: f.readOnlyOnEdit,
      editOnly: f.editOnly,
      rowSpec: f.rowSpec,
      rowNoun: f.rowNoun,
      orderKey: f.orderKey,
      orderStart: f.orderStart,
      intValue: f.intValue,
      dependsOn: f.dependsOn,
      choiceMap: f.choiceMap,
    );

/// [source] without its start date and with [changes] applied by key.
FormSpec rulesWithout(FormSpec source, {Map<String, FieldSpec> changes = const {}}) => FormSpec(
      name: source.name,
      label: source.label,
      fields: [
        for (final f in source.fields)
          if (f.key != 'effective_from') changes[f.key] ?? f,
      ],
    );
