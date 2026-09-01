package com.persona.ai

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat

class PersonaServerService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val apiKey = intent?.getStringExtra(EXTRA_API_KEY) ?: ByokStore(this).getApiKey()
        startForeground(NOTIFICATION_ID, buildNotification(getString(R.string.server_starting)))

        Thread {
            val ok = LocalPersonaServer.start(this, apiKey)
            if (ok) {
                LocalPersonaServer.waitUntilReady(60_000)
            }
            val notification = if (LocalPersonaServer.isHealthy()) {
                buildNotification(getString(R.string.server_running))
            } else {
                buildNotification(getString(R.string.server_failed))
            }
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.notify(NOTIFICATION_ID, notification)
        }.start()

        return START_STICKY
    }

    private fun buildNotification(text: String): Notification {
        createChannel()
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_launcher_logo)
            .setOngoing(true)
            .build()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                getString(R.string.server_channel_name),
                NotificationManager.IMPORTANCE_LOW,
            )
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(channel)
        }
    }

    companion object {
        const val EXTRA_API_KEY = "api_key"
        private const val CHANNEL_ID = "persona_local_server"
        private const val NOTIFICATION_ID = 8765

        fun start(context: Context, apiKey: String) {
            val intent = Intent(context, PersonaServerService::class.java).apply {
                putExtra(EXTRA_API_KEY, apiKey)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }
    }
}
