import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/api/api_error.dart';
import '../../../core/auth/permissions.dart';
import '../../../core/forms/choice_sources.dart';
import '../../../core/providers.dart';
import '../../../core/resource/resource_screens.dart';
import '../../../core/time.dart';
import '../../../core/widgets/ui.dart';
import '../../auth/state/auth_controller.dart';
import '../../employees/presentation/employee_picker_sheet.dart';
import '../../organisation/domain/org_resources.dart';
import '../../profile/data/employee_repository.dart';
import '../data/geofence_repository.dart';
import '../data/location_provider.dart';
import '../domain/geofence_admin.dart';
import '../domain/punch_location.dart';

/// Workplace geofences — mirrors `apps/web/src/app/app/attendance-geofences/page.tsx`. A workplace
/// is a branch with coordinates and a radius; this screen shows where each is used, manages the
/// extra workplaces an employee may punch at, and lets HR review location attempts. On a phone a
/// workplace's location can also be taken from where the user is standing. The API authorises
/// every action; hiding controls here is convenience only.
class GeofencesScreen extends ConsumerStatefulWidget {
  const GeofencesScreen({super.key});

  @override
  ConsumerState<GeofencesScreen> createState() => _GeofencesScreenState();
}

/// The location is the centre everyone is measured from, so it must be better than a punch needs.
const _workplaceFixPolicy = GeofencePolicyMe(mode: 'REQUIRED', maxAccuracyM: 50, maxAgeSeconds: 60);

String _describeFailure(LocationCaptureFailed f) => switch (f.failure) {
      LocationFailure.servicesDisabled => 'Turn on location services and try again.',
      LocationFailure.permissionDenied || LocationFailure.permissionDeniedForever => 'Allow location access for this app and try again.',
      LocationFailure.timeout => 'Could not get a location in time. Try again somewhere with a clearer view of the sky.',
      LocationFailure.poorAccuracy => 'GPS accuracy is ${formatMetres(f.accuracyM)}, which is too imprecise for a workplace centre. It needs to be 50 m or better.',
      LocationFailure.mockLocation => 'This device is reporting a simulated location, so it cannot be used.',
      _ => 'Could not get a location. Try again.',
    };

class _GeofencesScreenState extends ConsumerState<GeofencesScreen> {
  List<GeofenceWorkplace>? _workplaces;
  List<WorkplaceAuthorization> _authorizations = const [];
  bool _loadingConfig = true;
  String? _configError;
  bool _saving = false;

  List<GeofenceAttempt>? _attempts;
  String? _attemptsError;
  bool _onlyRejected = true;
  bool _attemptsHasNext = false;
  int _attemptsPage = 1;
  bool _loadingMore = false;
  int _attemptsRequest = 0;

  Map<String, String> _names = const {};
  Employee? _newEmployee;
  String? _newBranch;

  GeofenceRepository get _repo => ref.read(geofenceRepositoryProvider);
  List<String> get _permissions => ref.read(authControllerProvider).user?.permissions ?? const [];
  bool get _canConfigure => _permissions.contains(attendancePolicyManage);
  bool get _canReview => _permissions.contains(attendanceViewAll);

  @override
  void initState() {
    super.initState();
    if (_canConfigure) _loadConfig();
    if (_canReview) _loadAttempts();
    if (_canConfigure || _canReview) _loadNames();
  }

  String _describe(Object e) => e is ApiError ? (e.code == 'STALE_RESOURCE' ? 'This branch was changed by someone else. Try again.' : (e.status == 403 ? "You don't have permission to do that." : e.message)) : 'Something went wrong.';

  void _toast(String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  /// Names are a convenience: someone without the directory still sees the rest of the screen.
  Future<void> _loadNames() async {
    try {
      final choices = await loadChoices(ref.read(apiClientProvider), const ['employees']);
      if (mounted) setState(() => _names = {for (final c in choices['employees'] ?? const []) c.value: c.label});
    } catch (_) {}
  }

  String _employee(String id) => _names[id] ?? 'Employee';

  Future<void> _loadConfig() async {
    setState(() {
      _loadingConfig = true;
      _configError = null;
    });
    try {
      final results = await Future.wait([_repo.listWorkplaces(), _repo.listAuthorizations()]);
      if (!mounted) return;
      setState(() {
        _workplaces = results[0] as List<GeofenceWorkplace>;
        _authorizations = results[1] as List<WorkplaceAuthorization>;
      });
    } catch (e) {
      if (mounted) setState(() => _configError = _describe(e));
    } finally {
      if (mounted) setState(() => _loadingConfig = false);
    }
  }

  /// A slower answer for the other filter never overwrites the current one.
  Future<void> _loadAttempts() async {
    final mine = ++_attemptsRequest;
    setState(() {
      _attempts = null;
      _attemptsError = null;
    });
    try {
      final page = await _repo.listAttempts(onlyRejected: _onlyRejected);
      if (!mounted || mine != _attemptsRequest) return;
      setState(() {
        _attempts = page.rows;
        _attemptsHasNext = page.hasNext;
        _attemptsPage = 1;
      });
    } catch (e) {
      if (mounted && mine == _attemptsRequest) setState(() => _attemptsError = _describe(e));
    }
  }

  Future<void> _loadMoreAttempts() async {
    final mine = _attemptsRequest;
    setState(() => _loadingMore = true);
    try {
      final page = await _repo.listAttempts(onlyRejected: _onlyRejected, page: _attemptsPage + 1);
      if (!mounted || mine != _attemptsRequest) return;
      setState(() {
        _attempts = [...?_attempts, ...page.rows];
        _attemptsHasNext = page.hasNext;
        _attemptsPage += 1;
      });
    } catch (e) {
      if (mounted) _toast(_describe(e));
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  Future<void> _reload() async {
    await Future.wait([if (_canConfigure) _loadConfig(), if (_canReview) _loadAttempts()]);
  }

  Future<void> _authorize() async {
    final employee = _newEmployee;
    final branch = _newBranch;
    if (employee == null || branch == null) {
      _toast('Choose an employee and a workplace.');
      return;
    }
    setState(() => _saving = true);
    try {
      await _repo.authorize(employeeId: employee.id, branchId: branch);
      if (!mounted) return;
      setState(() {
        _names = {..._names, employee.id: employee.fullName.isEmpty ? employee.employeeCode : employee.fullName};
        _newEmployee = null;
        _newBranch = null;
      });
      _toast('Workplace authorised. The employee can now punch there.');
      await _loadConfig();
    } catch (e) {
      if (mounted) _toast(_describe(e));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _remove(WorkplaceAuthorization a, String workplace) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove this authorisation?'),
        content: Text('${_employee(a.employeeId)} will no longer be able to punch at $workplace.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Cancel')),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).colorScheme.error), onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Remove')),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    setState(() => _saving = true);
    try {
      await _repo.removeAuthorization(a.id);
      if (!mounted) return;
      _toast('Authorisation removed.');
      await _loadConfig();
    } catch (e) {
      if (mounted) _toast(_describe(e));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _editBranch(GeofenceWorkplace w) async {
    await Navigator.of(context).push(MaterialPageRoute(builder: (_) => ResourceDetailScreen(config: branchResource(), initial: {'id': w.branchId, 'name': w.name})));
    if (mounted) await _loadConfig();
  }

  Future<void> _useMyLocation(GeofenceWorkplace w) async {
    setState(() => _saving = true);
    final LocationCaptureResult result;
    try {
      result = await ref.read(locationCaptureProvider).capture(_workplaceFixPolicy);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
    if (!mounted) return;
    switch (result) {
      case LocationCaptureFailed():
        _toast(_describeFailure(result));
      case LocationCaptured(:final location):
        final radius = await showDialog<int>(context: context, builder: (_) => _ConfirmLocationDialog(workplace: w, location: location));
        if (radius == null || !mounted) return;
        setState(() => _saving = true);
        try {
          await _repo.setWorkplaceLocation(branchId: w.branchId, latitude: location.latitude, longitude: location.longitude, radiusM: radius);
          if (!mounted) return;
          _toast('${w.name} location saved.');
          await _loadConfig();
        } catch (e) {
          if (mounted) _toast(_describe(e));
        } finally {
          if (mounted) setState(() => _saving = false);
        }
    }
  }

  Future<void> _openMap(double latitude, double longitude) async {
    final ok = await launchUrl(workplaceMapLink(latitude, longitude), mode: LaunchMode.externalApplication);
    if (!ok && mounted) _toast('Could not open the map.');
  }

  @override
  Widget build(BuildContext context) {
    if (!_canConfigure && !_canReview) {
      return Scaffold(
        appBar: AppBar(title: const Text('Workplace Geofences')),
        body: const StateMessage(icon: Icons.location_off_outlined, title: 'No access', message: 'You need the attendance policy or attendance view-all permission to manage workplace geofences.'),
      );
    }
    final muted = TextStyle(fontSize: 13, color: Theme.of(context).colorScheme.onSurfaceVariant);
    return Scaffold(
      appBar: AppBar(title: const Text('Workplace Geofences')),
      body: RefreshIndicator(
        onRefresh: _reload,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text('Approved workplaces for location-checked attendance. A device-reported location is evidence, not proof of presence.', style: muted),
            if (_canConfigure) ...[const SizedBox(height: 16), ..._workplacesSection(muted), const SizedBox(height: 16), ..._authorizationsSection(muted)],
            if (_canReview) ...[const SizedBox(height: 16), ..._attemptsSection(muted)],
          ],
        ),
      ),
    );
  }

  List<Widget> _workplacesSection(TextStyle muted) {
    final canEditBranch = _permissions.contains(orgBranchManage);
    final workplaces = _workplaces;
    return [
      const SectionHeader('Workplaces'),
      if (_loadingConfig && workplaces == null)
        const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5)))
      else if (_configError != null)
        StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: "Couldn't load workplaces", message: _configError, actionLabel: 'Retry', onAction: _loadConfig)
      else if (workplaces == null || workplaces.isEmpty)
        const StateMessage(icon: Icons.location_on_outlined, title: 'No branches yet', message: 'A workplace is a branch with coordinates and a radius. Create a branch first.')
      else ...[
        for (final w in workplaces)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: AppCard(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text(w.name, style: const TextStyle(fontWeight: FontWeight.w700))),
                  StatusChip(label: w.statusLabel, tone: !w.configured ? Tone.warning : (w.isActive ? Tone.success : Tone.neutral)),
                ]),
                const SizedBox(height: 6),
                if (w.latitude != null && w.longitude != null)
                  InkWell(
                    onTap: () => _openMap(w.latitude!, w.longitude!),
                    child: Text('${w.latitude!.toStringAsFixed(5)}, ${w.longitude!.toStringAsFixed(5)}', style: TextStyle(color: Theme.of(context).colorScheme.primary, decoration: TextDecoration.underline)),
                  )
                else
                  Text('No location set', style: muted),
                const SizedBox(height: 2),
                Text('Radius ${w.radiusM == null ? '—' : '${w.radiusM} m'} · ${w.assignedEmployeeCount} assigned · ${w.authorizedEmployeeCount} also authorised', style: muted),
                if (canEditBranch) ...[
                  const SizedBox(height: 8),
                  Wrap(spacing: 8, children: [
                    OutlinedButton(onPressed: _saving ? null : () => _useMyLocation(w), child: const Text('Use my current location')),
                    TextButton(onPressed: _saving ? null : () => _editBranch(w), child: const Text('Edit branch')),
                  ]),
                ],
              ]),
            ),
          ),
        Text('A branch with employees assigned cannot be deactivated; one that is an extra authorised workplace is blocked until those authorisations are removed.', style: TextStyle(fontSize: 12, color: muted.color)),
      ],
    ];
  }

  List<Widget> _authorizationsSection(TextStyle muted) {
    final usable = [for (final w in _workplaces ?? const <GeofenceWorkplace>[]) if (w.usable) w];
    final names = {for (final w in _workplaces ?? const <GeofenceWorkplace>[]) w.branchId: w.name};
    return [
      const SectionHeader('Extra workplaces for individual employees'),
      Text('Employees can always punch at the branch on their assignment. Add another approved workplace here for people who legitimately work across locations. Employees cannot choose a workplace themselves.', style: muted),
      const SizedBox(height: 10),
      AppCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          OutlinedButton.icon(
            onPressed: _saving
                ? null
                : () async {
                    final picked = await pickEmployee(context);
                    if (picked != null && mounted) setState(() => _newEmployee = picked);
                  },
            icon: const Icon(Icons.person_search_outlined),
            label: Text(_newEmployee == null ? 'Choose an employee' : (_newEmployee!.fullName.isEmpty ? _newEmployee!.employeeCode : _newEmployee!.fullName), maxLines: 1, overflow: TextOverflow.ellipsis),
          ),
          const SizedBox(height: 10),
          DropdownButtonFormField<String>(
            value: _newBranch,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Workplace', helperText: 'Only active branches with coordinates and a radius.'),
            items: [for (final w in usable) DropdownMenuItem(value: w.branchId, child: Text(w.name, overflow: TextOverflow.ellipsis))],
            onChanged: _saving ? null : (v) => setState(() => _newBranch = v),
          ),
          const SizedBox(height: 10),
          FilledButton(onPressed: _saving ? null : _authorize, child: Text(_saving ? 'Saving…' : 'Authorise')),
          const SizedBox(height: 12),
          if (_authorizations.isEmpty)
            Text('No extra workplaces have been authorised.', style: muted)
          else
            for (final a in _authorizations)
              ListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                title: Text(_employee(a.employeeId)),
                subtitle: Text(names[a.branchId] ?? 'Workplace'),
                trailing: TextButton(onPressed: _saving ? null : () => _remove(a, names[a.branchId] ?? 'this workplace'), child: const Text('Remove')),
              ),
        ]),
      ),
    ];
  }

  List<Widget> _attemptsSection(TextStyle muted) {
    final attempts = _attempts;
    final zone = ref.read(authControllerProvider).user?.companyTimezone ?? 'Asia/Kolkata';
    final scheme = Theme.of(context).colorScheme;
    return [
      const SectionHeader('Location attempts'),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        dense: true,
        title: const Text('Rejected only'),
        value: _onlyRejected,
        onChanged: (v) {
          setState(() => _onlyRejected = v);
          _loadAttempts();
        },
      ),
      Text('A rejected attempt never becomes attendance by itself. If the employee was genuinely at work, correct their attendance through the regularization workflow, which requires a reason and is audited.', style: muted),
      const SizedBox(height: 10),
      if (_attemptsError != null)
        StateMessage(icon: Icons.error_outline_rounded, tone: Tone.danger, title: "Couldn't load attempts", message: _attemptsError, actionLabel: 'Retry', onAction: _loadAttempts)
      else if (attempts == null)
        const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5)))
      else if (attempts.isEmpty)
        StateMessage(icon: Icons.location_on_outlined, title: _onlyRejected ? 'No rejected attempts' : 'No attempts recorded', message: 'Attempts appear here once a policy using Optional or Required location checks is in use.')
      else ...[
        for (final a in attempts)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: AppCard(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text(_employee(a.employeeId), style: const TextStyle(fontWeight: FontWeight.w700))),
                  Text(a.accepted ? 'Allowed' : 'Rejected', style: TextStyle(fontWeight: FontWeight.w700, color: a.accepted ? null : scheme.error)),
                ]),
                const SizedBox(height: 4),
                Text(geofenceOutcomeLabel(a.outcome)),
                if (a.clientError != null) Text('Phone reported: ${a.clientError!.replaceAll('_', ' ').toLowerCase()}', style: muted),
                const SizedBox(height: 4),
                Text('${formatDateTime(a.createdAt, zone)} · Punch ${a.direction}', style: muted),
                Text('Distance ${formatMetres(a.distanceM)} of ${formatMetres(a.radiusM)} · GPS accuracy ${formatMetres(a.accuracyM)} · ${a.mode}', style: muted),
              ]),
            ),
          ),
        if (_attemptsHasNext) TextButton(onPressed: _loadingMore ? null : _loadMoreAttempts, child: Text(_loadingMore ? 'Loading…' : 'Load more')),
      ],
    ];
  }
}

/// Shows the reading and asks for the radius. Resolves to the radius, or null if cancelled.
class _ConfirmLocationDialog extends StatefulWidget {
  const _ConfirmLocationDialog({required this.workplace, required this.location});
  final GeofenceWorkplace workplace;
  final PunchLocation location;

  @override
  State<_ConfirmLocationDialog> createState() => _ConfirmLocationDialogState();
}

class _ConfirmLocationDialogState extends State<_ConfirmLocationDialog> {
  late final _radius = TextEditingController(text: '${widget.workplace.radiusM ?? 100}');
  String? _error;

  @override
  void dispose() {
    _radius.dispose();
    super.dispose();
  }

  void _save() {
    final value = int.tryParse(_radius.text.trim());
    if (value == null || value < 1 || value > 100000) {
      setState(() => _error = 'Enter a radius from 1 to 100000 metres.');
      return;
    }
    Navigator.of(context).pop(value);
  }

  @override
  Widget build(BuildContext context) {
    final l = widget.location;
    return AlertDialog(
      title: Text('Set ${widget.workplace.name} here?'),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${l.latitude.toStringAsFixed(5)}, ${l.longitude.toStringAsFixed(5)}'),
          Text('GPS accuracy ${formatMetres(l.accuracyM)}'),
          const SizedBox(height: 10),
          const Text('Do this while standing at the workplace. Every punch checked against this branch will be measured from this point.'),
          const SizedBox(height: 10),
          TextField(
            controller: _radius,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            decoration: InputDecoration(labelText: 'Radius (metres)', errorText: _error),
          ),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(onPressed: _save, child: const Text('Save location')),
      ],
    );
  }
}
