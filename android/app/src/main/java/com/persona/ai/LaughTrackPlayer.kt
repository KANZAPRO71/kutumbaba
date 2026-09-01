package com.persona.ai

import android.content.Context
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import android.util.Log

/** Memutar efek tertawa penonton (res/raw/laugh.mp3) setelah punchline mop. */
class LaughTrackPlayer(context: Context) {

    private val appContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())
    private var mediaPlayer: MediaPlayer? = null

    fun putarSuaraTertawa(delayMs: Long = LAUGH_DELAY_MS) {
        mainHandler.postDelayed({ playNow() }, delayMs)
    }

    private fun playNow() {
        try {
            mediaPlayer?.release()
            mediaPlayer = MediaPlayer.create(appContext, R.raw.laugh)?.apply {
                setVolume(0.16f, 0.16f)
                setOnCompletionListener {
                    it.release()
                    if (mediaPlayer === it) {
                        mediaPlayer = null
                    }
                }
                start()
            }
            if (mediaPlayer == null) {
                Log.w(TAG, "laugh.mp3 tidak ditemukan di res/raw")
            }
        } catch (e: Exception) {
            Log.w(TAG, "Gagal memutar laugh track", e)
        }
    }

    fun release() {
        mainHandler.removeCallbacksAndMessages(null)
        mediaPlayer?.release()
        mediaPlayer = null
    }

    companion object {
        private const val TAG = "LaughTrackPlayer"
        const val LAUGH_DELAY_MS = 500L
    }
}
