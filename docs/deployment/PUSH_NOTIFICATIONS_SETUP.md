# Push notifications: setup

Push is built end to end but **off until Firebase is configured**. Without the steps below the
app builds and runs normally; in-app notifications and the 30-second foreground poll still work.

## How it works

1. The app signs in, asks the OS for notification permission, gets an FCM token and registers it:
   `POST /v1/notifications/devices`.
2. When the API creates a notification (and `PUSH_PROVIDER=fcm`), a Celery task
   (`notification.send_push`) sends it to the recipient's registered phones through FCM.
3. Tapping the push opens the notification's screen (`action_url`) and marks it read.
4. Signing out calls `POST /v1/notifications/devices/unregister` while the session is still valid.

Dead tokens (FCM says unregistered) are deleted by the worker. A session that expires instead of
signing out cannot unregister; the token is dropped when FCM reports it dead or when the next
person signs in on that phone.

## One-time setup

1. **Firebase project** (console.firebase.google.com). Add an Android app with package
   `com.staffspectrum.hrms_mobile` and an iOS app with bundle ID `com.staffspectrum.hrmsMobile`.
2. **Android:** download `google-services.json` into `apps/mobile/android/app/`. The Gradle
   plugin is applied only when that file exists.
3. **iOS:** download `GoogleService-Info.plist` into `apps/mobile/ios/Runner/` (add it to the
   Runner target in Xcode). In Xcode enable the *Push Notifications* capability and the
   *Background Modes → Remote notifications* mode. Upload an APNs authentication key (Apple
   Developer → Keys) in Firebase → Project settings → Cloud Messaging.
4. **Server:** create a service-account key (Firebase → Project settings → Service accounts) and
   give the **worker** (not only the API) these settings:
   - `PUSH_PROVIDER=fcm`
   - `FCM_PROJECT_ID=<project id>` (optional; read from the key if omitted)
   - `FCM_SERVICE_ACCOUNT_JSON=<the key's JSON>` or `FCM_SERVICE_ACCOUNT_FILE=<mounted path>`
5. Run the API migration (`20261124090000`, table `device_token`).

## Checking it

- Sign in on a phone, then `SELECT count(*) FROM device_token;` should show a row.
- Create a notification for that user (e.g. approve their leave) with the app in the background.
- Worker logs: `push_send_rejected` / `push_send_failed` / `push_config_*` explain a miss.

## Known limits

- Delivery is best-effort and at-most-once, like the other post-commit work in the API.
- Android shows pushes on Firebase's default channel. A dedicated high-importance channel (for
  heads-up alerts) would need `flutter_local_notifications`; not added yet.
- `google-services.json` / `GoogleService-Info.plist` are client config, not secrets, but are
  per-environment: use separate Firebase projects for staging and production builds.
