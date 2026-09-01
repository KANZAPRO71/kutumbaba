package com.persona.ai

import android.util.Log
import com.chaquo.python.Python
import org.json.JSONObject

/**
 * Raja Mop randomizer — ambil mop acak dari database JSON.
 *
 * Primary: Python engine (papua_mops + database_papua.json) via Chaquopy.
 * Fallback: parse [database_papua.json] string lokal kalau Python belum siap.
 */
object MopRandomizer {

    private const val TAG = "MopRandomizer"
    private const val FALLBACK =
        "Adoo kawan, sa pung ingatan lagi penuh, tunggu sa ingat-ingat dulu ee!"

    /** Setara `ambilMopAcakDariDatabase` — delegasi ke Python Raja Mop engine. */
    fun ambilMopAcakDariDatabase(konteksLokalJson: String? = null): String {
        if (!konteksLokalJson.isNullOrBlank()) {
            parseJsonMop(konteksLokalJson)?.let { return it }
        }
        return ambilMopAcakPython()
    }

    fun ambilMopAcakPython(): String {
        return try {
            val module = Python.getInstance().getModule("persona_ai.android.bootstrap")
            module.callAttr("ambil_mop_acak").toString()
        } catch (e: Exception) {
            Log.w(TAG, "Python mop randomizer failed, using fallback", e)
            FALLBACK
        }
    }

    private fun parseJsonMop(json: String): String? {
        return try {
            val jsonObject = JSONObject(json)
            val mopArray = jsonObject.getJSONArray("mop_list")
            if (mopArray.length() <= 0) return null
            val randomIndex = (0 until mopArray.length()).random()
            mopArray.getString(randomIndex)
        } catch (e: Exception) {
            Log.w(TAG, "JSON mop parse failed", e)
            null
        }
    }
}
