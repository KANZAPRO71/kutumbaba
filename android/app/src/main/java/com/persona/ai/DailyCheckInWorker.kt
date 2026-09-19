package com.persona.ai

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import java.net.HttpURLConnection
import java.net.URL

/**
 * Soft daily reminder — opens app; skips if local API says user already talked today.
 */
class DailyCheckInWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        if (!CheckInScheduler.remindersEnabled(applicationContext)) {
            return Result.success()
        }
        val checkIn = fetchCheckInFromApi() ?: return Result.success()
        if (!checkIn.show) {
            return Result.success()
        }
        showNotification(checkIn.message)
        return Result.success()
    }

    private data class CheckInPayload(val show: Boolean, val message: String)

    private fun fetchCheckInFromApi(): CheckInPayload? {
        return try {
            val url = URL("${LocalPersonaServer.LOCAL_BASE_URL}/api/companion/check-in")
            val conn = url.openConnection() as HttpURLConnection
            conn.connectTimeout = 4000
            conn.readTimeout = 4000
            conn.requestMethod = "GET"
            if (conn.responseCode != 200) {
                return null
            }
            val body = conn.inputStream.bufferedReader().readText()
            conn.disconnect()
            val json = org.json.JSONObject(body)
            val show = json.optBoolean("show", false)
            val talkedToday = json.optBoolean("talked_today", false)
            if (talkedToday || !show) {
                return CheckInPayload(show = false, message = "")
            }
            val message = json.optString("message", "").trim()
            CheckInPayload(show = true, message = message)
        } catch (_: Exception) {
            null
        }
    }

    private fun showNotification(message: String) {
        val channelId = CHANNEL_ID
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "Papua AI",
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply {
                description = "Check-in ngobrol harian — opsional"
            }
            val mgr = applicationContext.getSystemService(NotificationManager::class.java)
            mgr.createNotificationChannel(channel)
        }

        val intent = Intent(applicationContext, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_FROM_CHECKIN, true)
        }
        val pending = PendingIntent.getActivity(
            applicationContext,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(applicationContext, channelId)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("Papua AI")
            .setContentText(
                if (message.isNotBlank()) message.take(180)
                else "Mau ngobrol sebentar? Tap untuk buka.",
            )
            .setStyle(
                NotificationCompat.BigTextStyle().bigText(
                    if (message.isNotBlank()) message else "Mau ngobrol sebentar? Tap untuk buka.",
                ),
            )
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()

        if (NotificationManagerCompat.from(applicationContext).areNotificationsEnabled()) {
            NotificationManagerCompat.from(applicationContext).notify(NOTIFICATION_ID, notification)
        }
    }

    companion object {
        const val CHANNEL_ID = "papua_daily_checkin"
        const val NOTIFICATION_ID = 4101
        const val EXTRA_FROM_CHECKIN = "from_daily_checkin"
    }
}
