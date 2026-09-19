package com.persona.ai

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.webkit.ConsoleMessage
import android.webkit.PermissionRequest
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "PersonaAI"
        private const val PERMISSION_REQUEST_MIC = 101
        private const val PERMISSION_REQUEST_NOTIFICATIONS = 102
        private const val PERMISSION_REQUEST_LOCATION = 103
    }

    private lateinit var webView: WebView
    private lateinit var errorView: LinearLayout
    private lateinit var tvStatus: TextView
    private lateinit var tvErrorMessage: TextView
    private lateinit var btnRetry: Button

    private lateinit var byokStore: ByokStore
    private lateinit var conversationModeStore: ConversationModeStore
    private lateinit var personaAndroidBridge: PersonaAndroidBridge
    private val papuaAiViewModel: PapuaAiViewModel by viewModels()
    private var pendingPermissionRequest: PermissionRequest? = null
    private var bootstrapping = false
    private var backendBaseUrl: String = LocalPersonaServer.LOCAL_BASE_URL

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        byokStore = ByokStore(this)
        conversationModeStore = ConversationModeStore(this)
        copyApiKeyFromWebEnv()

        webView = findViewById(R.id.webView)
        errorView = findViewById(R.id.errorView)
        tvStatus = findViewById(R.id.tvStatus)
        tvErrorMessage = findViewById(R.id.tvErrorMessage)
        btnRetry = findViewById(R.id.btnRetry)

        setupWebView()
        setupListeners()
        setupBackNavigation()
        checkMicrophonePermission()
        maybeRequestLocationPermission()
        maybeRequestNotificationPermission()
        bootstrapAndLoad()
    }

    private fun copyApiKeyFromWebEnv() {
        byokStore.seedFromProjectEnv(BuildConfig.GEMINI_API_KEY)
        if (byokStore.hasApiKey()) {
            Log.i(TAG, "API key ready (from web .env)")
        } else {
            Log.w(TAG, "No API key in .env — set GEMINI_API_KEY in project .env then rebuild APK")
        }
    }

    private fun bootstrapAndLoad() {
        if (bootstrapping) return
        bootstrapping = true
        hideErrorView()
        webView.visibility = View.VISIBLE
        tvErrorMessage.text = getString(R.string.server_starting)
        tvStatus.text = getString(R.string.status_local_backend)

        LocalPersonaServer.start(this, byokStore.getApiKey())
        Thread {
            LocalPersonaServer.waitUntilReady(120_000)
            val localOk = LocalPersonaServer.isHealthy()
            runOnUiThread {
                bootstrapping = false
                if (localOk) {
                    backendBaseUrl = LocalPersonaServer.LOCAL_BASE_URL
                    loadApp()
                } else {
                    val detail = PythonBridge.lastStartError?.let { "\n$it" } ?: ""
                    showBootstrapError(getString(R.string.error_server_start) + detail)
                }
            }
        }.start()
    }

    private fun loadApp() {
        tvStatus.text = getString(R.string.status_ready)
        hideErrorView()
        webView.visibility = View.VISIBLE
        val url = "${backendBaseUrl}?app=1"
        Log.i(TAG, "Loading Papua AI: $url")
        webView.loadUrl(url)
    }

    private fun hideErrorView() {
        errorView.visibility = View.GONE
        errorView.isClickable = false
        errorView.isFocusable = false
        webView.visibility = View.VISIBLE
        webView.elevation = 4f
        webView.bringToFront()
        webView.requestFocus()
    }

    private fun showBootstrapError(message: String) {
        tvErrorMessage.text = message
        tvStatus.text = getString(R.string.status_local_backend)
        webView.visibility = View.GONE
        errorView.visibility = View.VISIBLE
        errorView.isClickable = true
        errorView.isFocusable = true
        errorView.bringToFront()
    }

    fun runWebUiAction(actionId: String) {
        val safe = actionId.replace("\\", "\\\\").replace("'", "\\'")
        webView.evaluateJavascript(
            """
            (function(){
              try {
                if (window.__personaTap) window.__personaTap('$safe');
              } catch (e) { console.log('uiTap err: ' + e); }
            })();
            """.trimIndent(),
            null,
        )
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        if (BuildConfig.DEBUG) {
            WebView.setWebContentsDebuggingEnabled(true)
        }
        webView.setBackgroundColor(Color.parseColor("#18181B"))

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            mediaPlaybackRequiresUserGesture = false
            allowFileAccess = true
            allowContentAccess = true
            cacheMode = WebSettings.LOAD_NO_CACHE
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            useWideViewPort = true
            loadWithOverviewMode = true
        }

        webView.isFocusable = true
        webView.isFocusableInTouchMode = true
        webView.isClickable = true
        webView.requestFocus()

        personaAndroidBridge =
            PersonaAndroidBridge(this, byokStore, papuaAiViewModel, conversationModeStore)
        webView.addJavascriptInterface(personaAndroidBridge, "PersonaAndroid")
        webView.addJavascriptInterface(
            AndroidWebCompatBridge(personaAndroidBridge),
            "Android",
        )

        webView.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                Log.i(TAG, "WebView requested: ${request.resources.joinToString()}")
                runOnUiThread {
                    if (hasMicrophonePermission()) {
                        request.grant(request.resources)
                    } else {
                        pendingPermissionRequest = request
                        ActivityCompat.requestPermissions(
                            this@MainActivity,
                            arrayOf(Manifest.permission.RECORD_AUDIO),
                            PERMISSION_REQUEST_MIC
                        )
                    }
                }
            }

            override fun onConsoleMessage(consoleMessage: ConsoleMessage): Boolean {
                Log.d(TAG, "[WebView] ${consoleMessage.message()} @${consoleMessage.lineNumber()}")
                return true
            }
        }

        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                hideErrorView()
                webView.visibility = View.VISIBLE
                webView.elevation = 4f
                webView.bringToFront()
                webView.requestFocus()
                syncWebByokStorage()
                unlockWebUiTouches()
            }

            @SuppressLint("WebViewClientOnReceivedSslError")
            override fun onReceivedSslError(
                view: WebView?,
                handler: SslErrorHandler?,
                error: SslError?
            ) {
                if (BuildConfig.DEBUG) {
                    handler?.proceed()
                } else {
                    Log.e(TAG, "SSL error (blocked in release): ${error?.primaryError}")
                    handler?.cancel()
                }
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                super.onReceivedError(view, request, error)
                if (request?.isForMainFrame == true) {
                    showBootstrapError(
                        "${getString(R.string.error_loading)}\n${error?.description ?: ""}"
                    )
                }
            }
        }
    }

    private fun unlockWebUiTouches() {
        webView.evaluateJavascript(
            """
            (function(){
              try {
                if (window.__personaUnlockUi) window.__personaUnlockUi();
              } catch (e) {}
            })();
            """.trimIndent(),
            null,
        )
    }

    private fun syncWebByokStorage() {
        val key = byokStore.getApiKey()
        if (key.length < 8) return
        val escaped = key.replace("\\", "\\\\").replace("'", "\\'")
        webView.evaluateJavascript(
            """
            (function(){
              try {
                var k = '$escaped';
                if (!k || k.length < 8) return;
                var cur = localStorage.getItem('persona_gemini_api_key') || '';
                if (!cur || cur.length < 8) localStorage.setItem('persona_gemini_api_key', k);
                if (window.__personaRetryHealth) window.__personaRetryHealth();
              } catch (e) {}
            })();
            """.trimIndent(),
            null,
        )
    }

    private fun setupListeners() {
        btnRetry.setOnClickListener { bootstrapAndLoad() }
    }

    private fun setupBackNavigation() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                webView.evaluateJavascript(
                    """
                    (function(){
                      var s = document.getElementById('settings');
                      if (s && !s.hidden && !s.classList.contains('hidden')) {
                        if (window.__personaTap) window.__personaTap('btnSettingsClose');
                        return 'settings';
                      }
                      return '';
                    })();
                    """.trimIndent(),
                ) { result ->
                    if (result.contains("settings")) return@evaluateJavascript
                    if (webView.canGoBack()) {
                        webView.goBack()
                    } else {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                    }
                }
            }
        })
    }

    private fun hasMicrophonePermission(): Boolean {
        return ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
    }

    private fun checkMicrophonePermission() {
        if (!hasMicrophonePermission()) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.RECORD_AUDIO),
                PERMISSION_REQUEST_MIC
            )
        }
    }

    private fun maybeRequestLocationPermission() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        ActivityCompat.requestPermissions(
            this,
            arrayOf(
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION,
            ),
            PERMISSION_REQUEST_LOCATION,
        )
    }

    private fun maybeRequestNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (!CheckInScheduler.remindersEnabled(this)) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.POST_NOTIFICATIONS),
            PERMISSION_REQUEST_NOTIFICATIONS,
        )
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PERMISSION_REQUEST_MIC) {
            if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                pendingPermissionRequest?.grant(pendingPermissionRequest!!.resources)
                pendingPermissionRequest = null
            } else {
                pendingPermissionRequest?.deny()
                pendingPermissionRequest = null
            }
        }
    }

    override fun onPause() {
        super.onPause()
        pauseWebContent()
        webView.onPause()
        webView.pauseTimers()
    }

    override fun onResume() {
        super.onResume()
        webView.onResume()
        webView.resumeTimers()
        resumeWebContent()
    }

    override fun onDestroy() {
        if (isFinishing) {
            destroyWebViewSafely()
        }
        super.onDestroy()
    }

    private fun pauseWebContent() {
        webView.evaluateJavascript(
            """
            (function(){
              try {
                if (window.__personaPauseUi) window.__personaPauseUi(false);
              } catch (e) {}
            })();
            """.trimIndent(),
            null,
        )
    }

    private fun resumeWebContent() {
        webView.evaluateJavascript(
            """
            (function(){
              try {
                if (window.__personaResumeUi) window.__personaResumeUi();
              } catch (e) {}
            })();
            """.trimIndent(),
            null,
        )
    }

    /** Tear down WebView + JS bridges to avoid Activity/WebView leaks (finishing only). */
    private fun destroyWebViewSafely() {
        pauseWebContent()
        try {
            webView.removeJavascriptInterface("PersonaAndroid")
            webView.removeJavascriptInterface("Android")
        } catch (e: Exception) {
            Log.w(TAG, "removeJavascriptInterface: ${e.message}")
        }
        try {
            webView.loadUrl("about:blank")
            webView.stopLoading()
            webView.webChromeClient = null
            webView.webViewClient = WebViewClient()
            (webView.parent as? ViewGroup)?.removeView(webView)
            webView.destroy()
        } catch (e: Exception) {
            Log.w(TAG, "WebView destroy: ${e.message}")
        }
        try {
            val py = com.chaquo.python.Python.getInstance()
            py.getModule("persona_ai.plugins.webview_bridge")
                .callAttr("on_app_lifecycle", "destroy")
        } catch (e: Exception) {
            Log.d(TAG, "webview_bridge destroy hook: ${e.message}")
        }
    }
}
