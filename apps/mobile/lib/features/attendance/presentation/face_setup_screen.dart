import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/api_error.dart';
import '../../home/presentation/employee_home_screen.dart' show FaceSetupCard;
import '../data/attendance_repository.dart';

/// "Face Attendance Setup" as its own screen - the destination of the "Face Enrollment Requested"
/// notification. It never trusts the notification: it reads the canonical enrollment status from
/// the server, then offers Start / Continue Enrollment through the same [FaceSetupCard] Home uses.
class FaceSetupScreen extends ConsumerStatefulWidget {
  const FaceSetupScreen({super.key});

  @override
  ConsumerState<FaceSetupScreen> createState() => _FaceSetupScreenState();
}

class _FaceSetupScreenState extends ConsumerState<FaceSetupScreen> {
  FaceEnrollmentStatus? _status;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = _status == null;
      _error = null;
    });
    try {
      final status = await ref.read(attendanceRepositoryProvider).getMyFaceEnrollment();
      if (mounted) setState(() => _status = status);
    } catch (e) {
      if (mounted) setState(() => _error = describeApiError(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final status = _status;
    return Scaffold(
      appBar: AppBar(title: const Text('Face Attendance Setup')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Padding(padding: const EdgeInsets.all(24), child: Column(mainAxisSize: MainAxisSize.min, children: [Text(_error!, textAlign: TextAlign.center), const SizedBox(height: 12), OutlinedButton(onPressed: _load, child: const Text('Try again'))])))
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(padding: const EdgeInsets.all(16), physics: const AlwaysScrollableScrollPhysics(), children: [
                    if (status != null && status.isEnrolled)
                      const Card(child: Padding(padding: EdgeInsets.all(16), child: Text('Your face is enrolled. You can use face verification when you punch.')))
                    else if (status != null)
                      FaceSetupCard(status: status, onChanged: _load),
                  ]),
                ),
    );
  }
}
