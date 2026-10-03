import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api/api_client.dart';

/// Overridden in `main()` once `ApiClient.getInstance()` resolves (it's async
/// — it opens the persisted cookie jar — so it can't be a plain sync
/// [Provider] body the way the rest of this app's dependencies are).
final apiClientProvider = Provider<ApiClient>((ref) {
  throw UnimplementedError('overridden in main() once ApiClient.getInstance() resolves');
});
