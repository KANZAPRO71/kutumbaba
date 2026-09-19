package com.persona.ai

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Build
import androidx.core.content.ContextCompat
import org.json.JSONObject
import kotlin.math.round

/** Chaquopy ↔ Python: device context for Live function calling. */
object DeviceContextBridge {

    @Volatile
    private var appContext: Context? = null

    @JvmStatic
    fun init(context: Context) {
        appContext = context.applicationContext
    }

    @JvmStatic
    fun getLocationSnapshotJson(): String {
        val ctx = appContext ?: return err("uninitialized")
        if (!hasLocationPermission(ctx)) {
            return err("location_permission_denied")
        }
        val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
            ?: return err("location_service_unavailable")
        val providers = listOf(
            LocationManager.GPS_PROVIDER,
            LocationManager.NETWORK_PROVIDER,
            LocationManager.PASSIVE_PROVIDER,
        )
        var best: Location? = null
        for (p in providers) {
            if (!lm.isProviderEnabled(p)) continue
            val loc = try {
                lm.getLastKnownLocation(p)
            } catch (_: SecurityException) {
                null
            } catch (_: Exception) {
                null
            } ?: continue
            if (best == null || loc.time > best.time) {
                best = loc
            }
        }
        if (best == null) {
            return err("location_unavailable")
        }
        return JSONObject().apply {
            put("ok", true)
            put("latitude", round4(best.latitude))
            put("longitude", round4(best.longitude))
            put("accuracy_m", best.accuracy.toDouble())
            put("timestamp_ms", best.time)
            put("provider", best.provider ?: "")
        }.toString()
    }

    @JvmStatic
    fun getTelemetryJson(): String {
        val ctx = appContext ?: return err("uninitialized")
        val status = JSONObject(getDeviceStatusJson())
        val out = JSONObject()
        out.put("ok", true)
        if (status.optBoolean("ok", false)) {
            out.put("battery_percent", status.optInt("battery_percent", -1))
            out.put("charging", status.optBoolean("charging", false))
            out.put("network", status.optString("network", "unknown"))
        }
        var speedMps = 0.0
        if (hasLocationPermission(ctx)) {
            val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
            if (lm != null) {
                var best: Location? = null
                for (p in listOf(
                        LocationManager.GPS_PROVIDER,
                        LocationManager.NETWORK_PROVIDER,
                        LocationManager.PASSIVE_PROVIDER,
                    )) {
                    if (!lm.isProviderEnabled(p)) continue
                    val loc = try {
                        lm.getLastKnownLocation(p)
                    } catch (_: SecurityException) {
                        null
                    } catch (_: Exception) {
                        null
                    } ?: continue
                    if (best == null || loc.time > best.time) best = loc
                }
                if (best != null) {
                    out.put("latitude", round4(best.latitude))
                    out.put("longitude", round4(best.longitude))
                    out.put("accuracy_m", best.accuracy.toDouble())
                    if (best.hasSpeed()) {
                        speedMps = best.speed.toDouble().coerceAtLeast(0.0)
                    }
                }
            }
        }
        val speedKmh = speedMps * 3.6
        out.put("speed_kmh", round4(speedKmh))
        out.put(
            "movement_mode",
            when {
                speedMps >= 4.0 -> "driving"
                speedMps >= 0.6 -> "walking"
                else -> "stationary"
            },
        )
        return out.toString()
    }

    @JvmStatic
    fun getDeviceStatusJson(): String {
        val ctx = appContext ?: return err("uninitialized")
        val batteryPct = batteryPercent(ctx)
        val charging = isCharging(ctx)
        val network = networkLabel(ctx)
        return JSONObject().apply {
            put("ok", true)
            put("battery_percent", batteryPct)
            put("charging", charging)
            put("network", network)
        }.toString()
    }

    private fun hasLocationPermission(ctx: Context): Boolean {
        val fine = ContextCompat.checkSelfPermission(
            ctx,
            android.Manifest.permission.ACCESS_FINE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED
        val coarse = ContextCompat.checkSelfPermission(
            ctx,
            android.Manifest.permission.ACCESS_COARSE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED
        return fine || coarse
    }

    private fun batteryPercent(ctx: Context): Int {
        val bm = ctx.getSystemService(Context.BATTERY_SERVICE) as? BatteryManager
        if (bm != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            val level = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
            if (level in 0..100) return level
        }
        val intent = ctx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = intent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = intent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        if (level >= 0 && scale > 0) {
            return (level * 100 / scale).coerceIn(0, 100)
        }
        return -1
    }

    private fun isCharging(ctx: Context): Boolean {
        val intent = ctx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val status = intent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        return status == BatteryManager.BATTERY_STATUS_CHARGING ||
            status == BatteryManager.BATTERY_STATUS_FULL
    }

    private fun networkLabel(ctx: Context): String {
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return "unknown"
        val network = cm.activeNetwork ?: return "offline"
        val caps = cm.getNetworkCapabilities(network) ?: return "unknown"
        return when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            else -> "other"
        }
    }

    private fun round4(v: Double): Double = round(v * 10_000.0) / 10_000.0

    private fun err(code: String): String = JSONObject().apply {
        put("ok", false)
        put("error", code)
    }.toString()
}
