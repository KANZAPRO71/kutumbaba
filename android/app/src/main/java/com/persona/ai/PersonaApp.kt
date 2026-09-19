package com.persona.ai

import android.app.Application

/** Application shell — Python starts on the backend server thread (see LocalPersonaServer). */
class PersonaApp : Application() {
    override fun onCreate() {
        super.onCreate()
        DeviceContextBridge.init(this)
        CheckInScheduler.schedule(this)
    }
}
