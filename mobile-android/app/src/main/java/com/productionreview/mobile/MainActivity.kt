package com.productionreview.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private const val API_BASE = "https://machineshop.duckdns.org/api"
private val Navy = Color(0xFF142B45)
private val Teal = Color(0xFF087F8C)
private val Canvas = Color(0xFFF2F5F8)
private val Muted = Color(0xFF627386)

private data class Account(val username: String, val fullName: String, val role: String)

private object ApiClient {
    private fun request(path: String, method: String, body: JSONObject? = null, token: String? = null): JSONObject {
        val connection = (URL(API_BASE + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 15000
            readTimeout = 20000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("User-Agent", "ProductionMobile/0.1.0")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
            if (!token.isNullOrBlank()) setRequestProperty("Authorization", "Bearer $token")
        }
        try {
            if (body != null) connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            val json = if (text.isBlank()) JSONObject() else JSONObject(text)
            if (code !in 200..299) {
                val detail = json.optString("detail").ifBlank { "Server returned HTTP $code" }
                throw IllegalStateException(detail)
            }
            return json
        } finally {
            connection.disconnect()
        }
    }

    fun login(username: String, password: String): Pair<String, Account> {
        val body = JSONObject().put("username", username).put("password", password)
        val response = request("/auth/login", "POST", body)
        val token = response.getString("access_token")
        val me = request("/auth/me", "GET", token = token)
        return token to Account(
            username = me.optString("username", username),
            fullName = me.optString("full_name", username),
            role = me.optString("role", "USER")
        )
    }

    fun logout(token: String) { request("/auth/logout", "POST", token = token) }

    fun currentAccount(token: String): Account {
        val me = request("/auth/me", "GET", token = token)
        return Account(me.optString("username"), me.optString("full_name"), me.optString("role"))
    }
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val sessionStore = SessionStore(this)
        setContent {
            var username by remember { mutableStateOf("") }
            var password by remember { mutableStateOf("") }
            var account by remember { mutableStateOf<Account?>(null) }
            var token by remember { mutableStateOf<String?>(null) }
            var busy by remember { mutableStateOf(false) }
            var message by remember { mutableStateOf("Connect securely to your production account.") }
            val scope = rememberCoroutineScope()

            LaunchedEffect(Unit) {
                val saved = withContext(Dispatchers.IO) { sessionStore.read() }
                if (!saved.isNullOrBlank()) {
                    busy = true
                    try {
                        val current = withContext(Dispatchers.IO) { ApiClient.currentAccount(saved) }
                        token = saved
                        account = current
                        message = "Connected to Production Review."
                    } catch (_: Exception) {
                        withContext(Dispatchers.IO) { sessionStore.clear() }
                        message = "Your saved session has expired. Please sign in again."
                    } finally { busy = false }
                }
            }

            MaterialTheme(colorScheme = lightColorScheme(primary=Teal, secondary=Navy, background=Canvas, surface=Color.White)) {
                Surface(Modifier.fillMaxSize(), color=Canvas) {
                    Column(Modifier.fillMaxSize()) {
                        Column(Modifier.fillMaxWidth().background(Navy).padding(horizontal=22.dp, vertical=24.dp)) {
                            Text("PRODUCTION REVIEW", color=Color(0xFFB9D5E5), fontSize=12.sp, fontWeight=FontWeight.Bold, letterSpacing=1.5.sp)
                            Spacer(Modifier.height(8.dp))
                            Text("Mobile Operations", color=Color.White, fontSize=25.sp, fontWeight=FontWeight.Bold)
                            Text("Shop-floor quality capture", color=Color(0xFFD7E2EC), fontSize=14.sp)
                        }
                        Column(Modifier.fillMaxSize().padding(18.dp), verticalArrangement=Arrangement.spacedBy(14.dp)) {
                            Text("SECURE ACCESS", color=Muted, fontSize=12.sp, fontWeight=FontWeight.Bold, letterSpacing=1.2.sp)
                            Card(Modifier.fillMaxWidth(), shape=RoundedCornerShape(16.dp), colors=CardDefaults.cardColors(containerColor=Color.White), elevation=CardDefaults.cardElevation(2.dp)) {
                                Column(Modifier.padding(20.dp), verticalArrangement=Arrangement.spacedBy(12.dp)) {
                                    if (account == null) {
                                        Text("Sign in", color=Navy, fontSize=21.sp, fontWeight=FontWeight.Bold)
                                        Text("Use your existing Production Review username and password.", color=Muted, fontSize=14.sp)
                                        OutlinedTextField(value=username, onValueChange={username=it}, label={Text("Username")}, singleLine=true, modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(value=password, onValueChange={password=it}, label={Text("Password")}, singleLine=true, visualTransformation=PasswordVisualTransformation(), keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Password), modifier=Modifier.fillMaxWidth())
                                        Button(
                                            onClick={
                                                if (username.isBlank() || password.isBlank()) {
                                                    message = "Enter both username and password."
                                                } else {
                                                    busy = true
                                                    message = "Signing in securely…"
                                                    scope.launch {
                                                        try {
                                                            val result = withContext(Dispatchers.IO) { ApiClient.login(username.trim(), password) }
                                                            withContext(Dispatchers.IO) { sessionStore.save(result.first) }
                                                            token = result.first
                                                            account = result.second
                                                            password = ""
                                                            message = "Signed in. Server access verified."
                                                        } catch (e: Exception) {
                                                            message = e.message ?: "Unable to connect. Check your internet connection."
                                                        } finally { busy = false }
                                                    }
                                                }
                                            },
                                            enabled=!busy,
                                            modifier=Modifier.fillMaxWidth().height(52.dp),
                                            shape=RoundedCornerShape(10.dp),
                                            colors=ButtonDefaults.buttonColors(containerColor=Teal)
                                        ) { Text(if (busy) "PLEASE WAIT…" else "SIGN IN", fontWeight=FontWeight.Bold) }
                                    } else {
                                        Text("Welcome", color=Navy, fontSize=21.sp, fontWeight=FontWeight.Bold)
                                        Text(account!!.fullName.ifBlank { account!!.username }, color=Navy, fontSize=17.sp)
                                        Text("Username: ${account!!.username}", color=Muted, fontSize=14.sp)
                                        Text("Role: ${account!!.role}", color=Muted, fontSize=14.sp)
                                        Text("Your access is controlled by the production server.", color=Muted, fontSize=14.sp)
                                        OutlinedButton(onClick={
                                            val oldToken = token
                                            scope.launch {
                                                busy = true
                                                try {
                                                    if (oldToken != null) withContext(Dispatchers.IO) { ApiClient.logout(oldToken) }
                                                } catch (_: Exception) { }
                                                withContext(Dispatchers.IO) { sessionStore.clear() }
                                                token = null
                                                account = null
                                                message = "Signed out."
                                                busy = false
                                            }
                                        }, enabled=!busy, modifier=Modifier.fillMaxWidth()) { Text("SIGN OUT") }
                                    }
                                }
                            }
                            Card(Modifier.fillMaxWidth(), shape=RoundedCornerShape(16.dp), colors=CardDefaults.cardColors(containerColor=Color.White)) {
                                Column(Modifier.padding(18.dp)) {
                                    Text("Connection", color=Navy, fontSize=16.sp, fontWeight=FontWeight.Bold)
                                    Spacer(Modifier.height(6.dp))
                                    Text(message, color=Muted, fontSize=14.sp)
                                    Spacer(Modifier.height(4.dp))
                                    Text("Server: machineshop.duckdns.org • HTTPS", color=Teal, fontSize=12.sp, fontWeight=FontWeight.Medium)
                                }
                            }
                            Spacer(Modifier.weight(1f))
                            Text("Secure access • Existing production records", color=Muted, fontSize=11.sp, modifier=Modifier.align(Alignment.CenterHorizontally))
                        }
                    }
                }
            }
        }
    }
}

