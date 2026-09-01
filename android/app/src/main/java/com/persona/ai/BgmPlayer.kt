package com.persona.ai

import android.content.Context
import android.media.AudioManager
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.ToneGenerator
import android.os.Handler
import android.os.Looper
import android.util.Log

/**
 * BGM tongkrongan — loop disko tanah (pelan) + burst jedag-jedug 3 detik saat punchline.
 * Pakai file mp3 di res/raw kalau ada; fallback ToneGenerator + WebView synth BGM.
 */
class BgmPlayer(context: Context) {

    private val appContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())
    private var loopPlayer: MediaPlayer? = null
    private var burstPlayer: MediaPlayer? = null
    private var toneGenerator: ToneGenerator? = null
    private var burstRunnable: Runnable? = null
    private var loopRunnable: Runnable? = null
    private var synthBeat = 0
    private var currentMode: String = MODE_OFF

    private fun rawId(name: String): Int =
        appContext.resources.getIdentifier(name, "raw", appContext.packageName)

    fun startLoop(mode: String) {
        stopLoop()
        currentMode = mode
        if (mode == MODE_OFF) return
        val asset = when (mode) {
            MODE_HIPHOP -> "bgm_hiphop_papua"
            else -> "bgm_disco_tanah"
        }
        val resId = rawId(asset)
        if (resId == 0) {
            Log.i(TAG, "BGM $asset tidak ada di res/raw — skip (no synth beep during voice)")
            return
        }
        stopSynthLoop()
        try {
            loopPlayer = MediaPlayer.create(appContext, resId)?.apply {
                isLooping = true
                setVolume(0.12f, 0.12f)
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                        .build()
                )
                start()
            }
        } catch (e: Exception) {
            Log.w(TAG, "Gagal loop BGM", e)
        }
    }

    fun stopLoop() {
        stopSynthLoop()
        try {
            loopPlayer?.stop()
            loopPlayer?.release()
        } catch (_: Exception) {
        }
        loopPlayer = null
        currentMode = MODE_OFF
    }

    /** Fallback disko tanah — ToneGenerator beat loop kalau belum ada mp3 di res/raw. */
    private fun startSynthLoop(mode: String) {
        stopSynthLoop()
        try {
            toneGenerator?.release()
            toneGenerator = ToneGenerator(AudioManager.STREAM_MUSIC, 48)
        } catch (e: Exception) {
            Log.w(TAG, "ToneGenerator BGM gagal", e)
            return
        }
        val intervalMs = if (mode == MODE_HIPHOP) 380L else 520L
        synthBeat = 0
        val runnable = object : Runnable {
            override fun run() {
                if (currentMode == MODE_OFF) return
                if (loopPlayer != null) return
                try {
                    val tone = if (synthBeat % 2 == 0) {
                        ToneGenerator.TONE_PROP_BEEP
                    } else {
                        ToneGenerator.TONE_PROP_ACK
                    }
                    val dur = (intervalMs * 0.65).toInt().coerceIn(100, 350)
                    toneGenerator?.startTone(tone, dur)
                } catch (_: Exception) {
                }
                synthBeat += 1
                mainHandler.postDelayed(this, intervalMs)
            }
        }
        loopRunnable = runnable
        mainHandler.post(runnable)
        Log.i(TAG, "BGM synth loop aktif mode=$mode")
    }

    private fun stopSynthLoop() {
        loopRunnable?.let { mainHandler.removeCallbacks(it) }
        loopRunnable = null
    }

    fun playJedagBurst(durationMs: Long = JEDAG_BURST_MS) {
        burstRunnable?.let { mainHandler.removeCallbacks(it) }
        val resId = rawId("jedag_jedug")
        if (resId != 0) {
            try {
                burstPlayer?.release()
                burstPlayer = MediaPlayer.create(appContext, resId)?.apply {
                    setVolume(0.35f, 0.35f)
                    setOnCompletionListener {
                        it.release()
                        if (burstPlayer === it) burstPlayer = null
                    }
                    start()
                }
            } catch (e: Exception) {
                Log.w(TAG, "Gagal jedag_jedug mp3", e)
            }
        }
        if (burstPlayer == null) {
            Log.i(TAG, "jedag_jedug tidak ada di res/raw — skip burst")
        }
    }

    /** @deprecated Synth ToneGenerator bentrok dengan AudioTrack voice — tidak dipakai. */
    @Suppress("unused")
    private fun playToneBurst(durationMs: Long) {
        try {
            toneGenerator?.release()
            toneGenerator = ToneGenerator(ToneGenerator.TONE_PROP_BEEP2, 60)
        } catch (e: Exception) {
            Log.w(TAG, "ToneGenerator gagal", e)
            return
        }
        var elapsed = 0L
        val step = 160L
        val runnable = object : Runnable {
            override fun run() {
                if (elapsed >= durationMs) {
                    burstRunnable = null
                    return
                }
                try {
                    toneGenerator?.startTone(
                        if ((elapsed / step) % 2L == 0L) ToneGenerator.TONE_PROP_BEEP
                        else ToneGenerator.TONE_PROP_BEEP2,
                        120
                    )
                } catch (_: Exception) {
                }
                elapsed += step
                mainHandler.postDelayed(this, step)
            }
        }
        burstRunnable = runnable
        mainHandler.post(runnable)
    }

    fun release() {
        burstRunnable?.let { mainHandler.removeCallbacks(it) }
        burstRunnable = null
        stopSynthLoop()
        stopLoop()
        try {
            burstPlayer?.release()
        } catch (_: Exception) {
        }
        burstPlayer = null
        try {
            toneGenerator?.release()
        } catch (_: Exception) {
        }
        toneGenerator = null
    }

    companion object {
        private const val TAG = "BgmPlayer"
        const val MODE_OFF = "off"
        const val MODE_DISKO = "disko_tanah"
        const val MODE_HIPHOP = "hiphop_papua"
        const val JEDAG_BURST_MS = 3000L
    }
}
