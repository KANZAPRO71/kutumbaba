package com.persona.ai

import android.app.Application
import androidx.lifecycle.AndroidViewModel

/**
 * Raja Mop — laugh track penonton setelah punchline selesai.
 *
 * Sesi Gemini Live di app ini lewat WebView + Python bridge; [onLiveTurnComplete]
 * dipanggil dari [PersonaAndroidBridge.playLaughTrack] saat server kirim laugh_track.
 */
class PapuaAiViewModel(application: Application) : AndroidViewModel(application) {

    private val laughPlayer = LaughTrackPlayer(application)
    private val bgmPlayer = BgmPlayer(application)

    fun putarSuaraTertawa() {
        laughPlayer.putarSuaraTertawa(LaughTrackPlayer.LAUGH_DELAY_MS)
    }

    fun startBgm(mode: String) {
        bgmPlayer.startLoop(mode)
    }

    fun stopBgm() {
        bgmPlayer.stopLoop()
    }

    fun playJedagJedug() {
        bgmPlayer.playJedagBurst(BgmPlayer.JEDAG_BURST_MS)
    }

    /** Setara turnComplete dari Gemini Live — jeda 0.5s lalu laugh track. */
    fun onLiveTurnComplete(laughTrack: Boolean) {
        if (laughTrack) {
            putarSuaraTertawa()
        }
    }

    override fun onCleared() {
        laughPlayer.release()
        bgmPlayer.release()
        super.onCleared()
    }
}
