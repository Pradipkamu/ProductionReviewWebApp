package com.productionreview.mobile

import android.os.Bundle
import android.content.Intent
import android.net.Uri
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.lifecycle.lifecycleScope
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Assignment
import androidx.compose.material.icons.filled.AssignmentLate
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Logout
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.net.URL
import java.io.IOException
import java.time.LocalDate
import java.time.Instant
import java.time.ZoneOffset

private const val API_BASE = "https://machineshop.duckdns.org/api"
private val Navy = Color(0xFF142B45)
private val Teal = Color(0xFF087F8C)
private val Canvas = Color(0xFFF2F5F8)
private val Muted = Color(0xFF627386)
private val Border = Color(0xFFE1E8EF)
private val Success = Color(0xFF16836B)
private val Warning = Color(0xFFE58A18)
private val Danger = Color(0xFFB3261E)

private data class Account(val username: String, val fullName: String, val role: String)
private data class Choice(val id: Int, val label: String, val extra: String = "")
private data class RouteChoice(val id: Int, val label: String)
private data class OeeLossDraft(
    val categoryId: Int? = null,
    val duration: String = "",
    val qty: String = "0",
    val remark: String = "",
    val saved: Boolean = false,
    val id: Int? = null,
    val category: String = "",
    val component: String = "",
    val startTime: String = "",
    val endTime: String = ""
)

private fun isAvailabilityOeeLoss(loss: OeeLossDraft, categories: List<Choice>): Boolean {
    val component = loss.component.ifBlank {
        categories.firstOrNull { it.id == loss.categoryId }?.extra.orEmpty()
    }
    return component.trim().equals("AVAILABILITY", ignoreCase = true)
}

private fun resolvedOeeLossQuantity(
    loss: OeeLossDraft,
    idealCycleSeconds: Double?,
    categories: List<Choice>
): Double {
    if (isAvailabilityOeeLoss(loss, categories)) {
        val minutes = loss.duration.toDoubleOrNull()?.coerceAtLeast(0.0) ?: 0.0
        val cycle = idealCycleSeconds?.takeIf { it > 0.0 } ?: return 0.0
        return minutes * 60.0 / cycle
    }
    return loss.qty.toDoubleOrNull()?.coerceAtLeast(0.0) ?: 0.0
}

private object ApiClient {
    private fun describeApiError(body: String, code: Int): String {
        fun valueText(value: Any?): String = when (value) {
            is String -> value.trim()
            is JSONObject -> listOf("message", "msg", "detail", "error_description", "error")
                .firstNotNullOfOrNull { key -> value.opt(key)?.let(::valueText)?.takeIf { it.isNotBlank() } }.orEmpty()
            is JSONArray -> (0 until value.length()).mapNotNull { index ->
                value.opt(index)?.let(::valueText)?.takeIf { it.isNotBlank() }
            }.distinct().joinToString("; ")
            else -> ""
        }
        val parsed = runCatching {
            val json = JSONObject(body)
            listOf("detail", "message", "error_description", "error")
                .firstNotNullOfOrNull { key -> json.opt(key)?.let(::valueText)?.takeIf { it.isNotBlank() } }.orEmpty()
        }.getOrElse { runCatching { valueText(JSONArray(body)) }.getOrDefault("") }
        if (parsed.isNotBlank()) return parsed
        return when (code) {
            400 -> "The request could not be accepted. Check the entered information."
            401 -> "Incorrect username or password, or your session is no longer valid."
            403 -> "Your account does not have permission to sign in."
            404 -> "The sign-in service could not be found. Contact the administrator."
            in 500..599 -> "The server encountered an error (HTTP $code). Please try again later."
            else -> "Sign-in failed (HTTP $code). Please check your details and try again."
        }
    }

    private fun requestText(path: String, method: String, body: JSONObject? = null, token: String? = null,
                             extraHeaders: Map<String, String> = emptyMap()): String {
        val connection = (URL(API_BASE + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 15000
            readTimeout = 25000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("User-Agent", "ProductionMobile/0.2.0")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
            if (!token.isNullOrBlank()) setRequestProperty("Authorization", "Bearer $token")
            extraHeaders.forEach { (name, value) -> setRequestProperty(name, value) }
        }
        try {
            if (body != null) connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) throw IllegalStateException(describeApiError(text, code))
            return text
        } catch (e: SocketTimeoutException) {
            throw IllegalStateException("Connection timed out. Check your internet connection and try again.", e)
        } catch (e: UnknownHostException) {
            throw IllegalStateException("Cannot reach the Production Review server. Check your internet connection.", e)
        } catch (e: IOException) {
            throw IllegalStateException("Network error while contacting the server: ${e.localizedMessage ?: "please try again"}.", e)
        } finally { connection.disconnect() }
    }

    private fun request(path: String, method: String, body: JSONObject? = null, token: String? = null,
                        extraHeaders: Map<String, String> = emptyMap()): JSONObject =
        JSONObject(requestText(path, method, body, token, extraHeaders))

    private fun array(path: String, token: String): JSONArray = JSONArray(requestText(path, "GET", token=token))

    fun login(username: String, password: String): Pair<String, Account> {
        val response = request("/auth/login", "POST", JSONObject().put("username", username).put("password", password))
        val token = response.getString("access_token")
        return token to currentAccount(token)
    }
    fun logout(token: String) { request("/auth/logout", "POST", token=token) }
    fun currentAccount(token: String): Account {
        val me = request("/auth/me", "GET", token=token)
        return Account(me.optString("username"), me.optString("full_name"), me.optString("role"))
    }

    fun loadChatConversations(token: String): JSONArray = array("/chat/conversations", token)
    fun loadChatEmployees(query: String, token: String): JSONArray =
        JSONArray(requestText("/chat/employees?q=" + java.net.URLEncoder.encode(query, "UTF-8"), "GET", token=token))
    fun createDirectChat(userId: Int, token: String): JSONObject =
        request("/chat/conversations/direct", "POST", JSONObject().put("user_id", userId), token)
    fun loadChatMessages(conversationId: Int, token: String): JSONArray =
        array("/chat/conversations/$conversationId/messages?limit=60", token)
    fun sendChatMessage(conversationId: Int, body: String, token: String): JSONObject =
        request("/chat/conversations/$conversationId/messages", "POST", JSONObject().put("body", body), token)
    fun loadMasters(token: String): Masters {
        val productsJson = array("/masters/products", token)
        val products = (0 until productsJson.length()).map { i ->
            val x=productsJson.getJSONObject(i)
            Choice(x.getInt("id"), "${x.optString("code")} • ${x.optString("name")}", x.optString("plant"))
        }
        val machinesJson = array("/masters/machines", token)
        val machines = (0 until machinesJson.length()).mapNotNull { i ->
            val x=machinesJson.getJSONObject(i)
            if (x.has("active") && !x.optBoolean("active")) null
            else if (x.has("is_active") && !x.optBoolean("is_active")) null
            else Choice(x.getInt("id"), "${x.optString("code")} • ${x.optString("name")}")
        }
        val phenomenaJson = array("/quality/phenomena", token)
        val phenomena = (0 until phenomenaJson.length()).map { i ->
            val x=phenomenaJson.getJSONObject(i)
            Choice(x.getInt("id"), x.optString("name"), x.optString("group"))
        }
        return Masters(products, machines, phenomena)
    }
    fun loadRoutes(productId: Int, date: String, token: String): List<RouteChoice> {
        val routes = array("/masters/routes/$productId?on_date=$date", token)
        val candidates = mutableListOf<Pair<String, List<RouteChoice>>>()
        for (i in 0 until routes.length()) {
            val route=routes.getJSONObject(i)
            val from=route.optString("effective_from")
            val to=route.optString("effective_to").takeIf { it.isNotBlank() && it!="null" }
            if (from.isNotBlank() && from <= date && (to == null || to >= date)) {
                val ops=route.optJSONArray("operations") ?: JSONArray()
                val list=(0 until ops.length()).mapNotNull { j ->
                    val op=ops.getJSONObject(j)
                    val operationId=op.optInt("route_operation_id")
                    val operationName=op.optString("operation").trim()
                    if(operationId>0 && operationName.isNotBlank()) {
                        RouteChoice(operationId, "${op.optInt("sequence_no")}. $operationName")
                    } else null
                }.distinctBy { it.id }
                candidates.add(from to list)
            }
        }
        return candidates.maxByOrNull { it.first }?.second ?: emptyList()
    }
    fun loadOeeMachines(routeOperationId: Int, date: String, token: String): List<Choice> {
        val response = request("/oee/available-machines?route_operation_id=$routeOperationId&production_date=$date", "GET", token=token)
        // Never accept fallback lists from older APIs: only an explicit mapped=true
        // response is valid for OEE operation/machine selection.
        if (!response.optBoolean("mapped", false)) return emptyList()
        val rows = response.optJSONArray("machines") ?: JSONArray()
        return (0 until rows.length()).mapNotNull { i ->
            val row = rows.getJSONObject(i)
            val id = row.optInt("id", 0)
            if (id <= 0) null else Choice(id, row.optString("code") + " • " + row.optString("name"))
        }.distinctBy { it.id }
    }
    fun loadOeeSummary(machineId: Int, date: String, shift: String, productId: Int, routeOperationId: Int, token: String): JSONObject =
        request("/oee/machine-summary?machine_id=$machineId&summary_date=$date&shift=$shift&product_id=$productId&route_operation_id=$routeOperationId", "GET", token=token)

    fun loadOeeRecentRecords(fromDate: String, toDate: String, shift: String, machineId: Int, productId: Int, routeOperationId: Int, token: String): JSONObject =
        request("/oee/recent-records?from_date=$fromDate&to_date=$toDate&shift=$shift&machine_id=$machineId&product_id=$productId&route_operation_id=$routeOperationId", "GET", token=token)

    fun saveOeeMachineEntry(payload: JSONObject, token: String): JSONObject =
        request("/oee/machine-entry", "POST", payload, token)

    fun saveOeeEntryWithLosses(
        entry: JSONObject, losses: JSONArray, token: String,
        entryId: Int? = null, correctionReason: String? = null
    ): JSONObject {
        val body = JSONObject().put("entry", entry).put("losses", losses)
        entryId?.let { body.put("entry_id", it) }
        correctionReason?.let { body.put("correction_reason", it) }
        return request("/oee/machine-entry-with-losses", "POST", body, token)
    }

    fun loadOeeEntryContext(productId: Int, operationId: Int, machineId: Int, date: String, shift: String, token: String): JSONObject =
        request("/oee/entry-context?product_id=$productId&route_operation_id=$operationId&machine_id=$machineId&production_date=$date&shift=$shift", "GET", token=token)

    fun correctOeeMachineEntry(entryId: Int, payload: JSONObject, reason: String, token: String): JSONObject =
        request("/oee/machine-entry/$entryId", "PUT", payload, token, mapOf("X-Change-Reason" to reason))

    fun correctOeeLoss(lossId: Int, payload: JSONObject, reason: String, token: String): JSONObject =
        request("/oee/loss-events/$lossId", "PUT", payload, token, mapOf("X-Change-Reason" to reason))

    fun loadOeeOperators(token: String): List<Choice> {
        val rows = array("/personnel", token)
        return (0 until rows.length()).map { i ->
            val row = rows.getJSONObject(i)
            Choice(row.getInt("id"), row.optString("full_name"))
        }
    }

    fun createOeeOperator(fullName: String, token: String): Pair<Choice, Boolean> {
        val parts = fullName.trim().split(Regex("\\s+")).filter { it.isNotBlank() }
        require(parts.size >= 2) { "Enter first name and surname." }
        val response = request("/personnel", "POST", JSONObject().put("first_name", parts.first()).put("last_name", parts.drop(1).joinToString(" ")), token)
        return Pair(Choice(response.getInt("id"), response.optString("full_name")), response.optBoolean("duplicate_warning"))
    }

    fun loadOeeManagement(
        fromDate: String, toDate: String, token: String,
        productId: Int? = null, routeOperationId: Int? = null, machineId: Int? = null
    ): JSONObject {
        val filters = buildString {
            productId?.let { append("&product_id=$it") }
            routeOperationId?.let { append("&route_operation_id=$it") }
            machineId?.let { append("&machine_id=$it") }
        }
        return request("/oee/management-summary?from_date=$fromDate&to_date=$toDate$filters", "GET", token=token)
    }

    fun loadOeeLossCategories(token: String): List<Choice> {
        val rows = array("/masters/loss-categories", token)
        return (0 until rows.length()).map { i ->
            val row = rows.getJSONObject(i)
            Choice(row.getInt("id"), row.optString("name"), row.optString("component"))
        }
    }

    fun saveOeeLoss(payload: JSONObject, token: String): JSONObject =
        request("/oee/loss-events", "POST", payload, token)

    fun raiseOeeLossAction(lossId: Int, token: String): JSONObject =
        request("/oee/loss-events/$lossId/raise-action", "POST",
            JSONObject().put("action_description", "Contain the loss, complete standard Why-Why analysis and implement corrective action")
                .put("target_oee", 0.85), token)

    fun loadPendingActions(token: String): List<ActionItem> {
        val rows = array("/actions/my-pending", token)
        return (0 until rows.length()).map { i ->
            val x=rows.getJSONObject(i)
            ActionItem(x.optInt("id"),x.optString("action_no"),x.optString("problem_description").ifBlank{x.optString("action_description")},x.optString("action_type"),x.optString("status"),x.optString("priority"),x.optString("due_at"),x.optBoolean("overdue"),x.optBoolean("requires_whywhy"),x.optInt("whywhy_completion_percent"))
        }
    }
    fun loadPendingActionGroups(token: String): List<ActionOwnerGroup> {
        val rows = array("/actions/admin/pending-by-user", token)
        return (0 until rows.length()).map { i ->
            val x = rows.getJSONObject(i)
            val actions = x.optJSONArray("actions") ?: JSONArray()
            val parsed = (0 until actions.length()).map { j ->
                val a = actions.getJSONObject(j)
                ActionItem(a.optInt("id"), a.optString("action_no"), a.optString("problem_description").ifBlank { a.optString("action_description") }, a.optString("action_type"), a.optString("status"), a.optString("priority"), a.optString("due_at"), a.optBoolean("overdue"), a.optBoolean("requires_whywhy"), a.optInt("whywhy_completion_percent"))
            }
            ActionOwnerGroup(x.optInt("user_id", -1).takeIf { it > 0 }, x.optString("full_name").ifBlank { "Unassigned" }, x.optString("role"), x.optInt("open_count"), x.optInt("overdue_count"), x.optInt("due_today_count"), parsed)
        }
    }

    fun loadActionPlan(id:Int,token:String): JSONObject = request("/actions/$id/plan","GET",token=token)
    fun loadActionHistory(id:Int,token:String): List<JSONObject> {
        val rows=array("/actions/$id/history",token)
        return (0 until rows.length()).map { rows.getJSONObject(it) }
    }
    fun downloadActionAttachment(actionId:Int,attachmentId:Int,fileName:String,cacheDir:File,token:String):File {
        val connection=(URL("$API_BASE/actions/$actionId/attachments/$attachmentId").openConnection() as HttpURLConnection).apply {
            requestMethod="GET";connectTimeout=15000;readTimeout=45000
            setRequestProperty("Accept","application/octet-stream")
            setRequestProperty("Authorization","Bearer $token")
        }
        try {
            val code=connection.responseCode
            if(code !in 200..299) {
                val body=connection.errorStream?.bufferedReader()?.use{it.readText()}.orEmpty()
                val detail=runCatching{JSONObject(body).optString("detail")}.getOrNull().orEmpty()
                throw IllegalStateException(detail.ifBlank{"Attachment download failed (HTTP $code)"})
            }
            val safeName=fileName.substringAfterLast('/').substringAfterLast(92.toChar()).replace(Regex("[^A-Za-z0-9._-]"),"_").ifBlank{"action_attachment_$attachmentId"}
            val target=File(cacheDir,"action_" + actionId + "_" + attachmentId + "_" + safeName)
            connection.inputStream.use{input->target.outputStream().use{output->input.copyTo(output)}}
            if(!target.exists()||target.length()==0L)throw IllegalStateException("Downloaded attachment is empty.")
            return target
        } finally { connection.disconnect() }
    }
    fun updateAction(id:Int,comment:String,status:String,token:String): JSONObject {
        val body=JSONObject().put("comment",comment).put("status",status)
        return request("/actions/$id","PATCH",body,token)
    }
    fun updateWhyWhy(id:Int,fields:JSONObject,token:String): JSONObject =
        request("/actions/$id/plan","PUT",fields,token)

    fun uploadActionEvidence(actionId:Int,file:File,token:String):JSONObject {
        val boundary="----ProductionMobile${System.currentTimeMillis()}"
        val connection=(URL("$API_BASE/actions/$actionId/attachments").openConnection() as HttpURLConnection).apply {
            requestMethod="POST";connectTimeout=15000;readTimeout=45000;doOutput=true
            setRequestProperty("Accept","application/json")
            setRequestProperty("Authorization","Bearer $token")
            setRequestProperty("Content-Type","multipart/form-data; boundary=$boundary")
        }
        try {
            connection.outputStream.use { out ->
                out.write("--$boundary\r\n".toByteArray())
                out.write("Content-Disposition: form-data; name=\"file\"; filename=\"${file.name}\"\r\n".toByteArray())
                out.write("Content-Type: application/octet-stream\r\n\r\n".toByteArray())
                file.inputStream().use{it.copyTo(out)}
                out.write("\r\n--$boundary--\r\n".toByteArray())
            }
            val code=connection.responseCode
            val stream=if(code in 200..299)connection.inputStream else connection.errorStream
            val body=stream?.bufferedReader()?.use{it.readText()}.orEmpty()
            if(code !in 200..299)throw IllegalStateException(runCatching{JSONObject(body).optString("detail")}.getOrNull().orEmpty().ifBlank{"Evidence upload failed (HTTP $code)"})
            return JSONObject(body)
        } finally { connection.disconnect() }
    }

    fun saveRejection(payload: JSONObject, token: String): JSONObject =
        request("/quality/daily", "POST", payload, token)

    fun loadRejectionTrend(productId: Int, fromDate: LocalDate, toDate: LocalDate, token: String): List<RejectionTrendPoint> {
        val rows = array("/quality/trend?from_date=$fromDate&to_date=$toDate&product_id=$productId", token)
        return (0 until rows.length()).map { index ->
            val row = rows.getJSONObject(index)
            RejectionTrendPoint(LocalDate.parse(row.getString("date")), row.optDouble("reject_qty", 0.0).toFloat())
        }
    }

    fun uploadRejectionPhoto(rejectionId: Int, file: File, token: String): JSONObject {
        val uploadFile = PhotoCompressor.prepare(file)
        val boundary = "----ProductionMobile${System.currentTimeMillis()}"
        val connection = (URL("$API_BASE/quality/daily/$rejectionId/attachments").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15000
            readTimeout = 45000
            doOutput = true
            setChunkedStreamingMode(64 * 1024)
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Authorization", "Bearer $token")
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        }
        try {
            connection.outputStream.use { output ->
                val header = "--$boundary\r\n" +
                    "Content-Disposition: form-data; name=\"file\"; filename=\"${uploadFile.name}\"\r\n" +
                    "Content-Type: image/jpeg\r\n\r\n"
                output.write(header.toByteArray(Charsets.UTF_8))
                uploadFile.inputStream().use { input -> input.copyTo(output) }
                output.write("\r\n--$boundary--\r\n".toByteArray(Charsets.UTF_8))
            }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) {
                val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull().orEmpty()
                throw IllegalStateException(detail.ifBlank { "Photo upload failed (HTTP $code)" })
            }
            return JSONObject(text)
        } finally {
            if (uploadFile != file) uploadFile.delete()
            connection.disconnect()
        }
    }
}
private fun userFriendlyOeeError(error: Exception, fallback: String): String {
    val detail = error.message.orEmpty()
    return when {
        error is java.net.UnknownHostException -> "Cannot reach the production server. Check your internet connection and tap Refresh OEE."
        error is java.net.SocketTimeoutException -> "The server is taking too long to respond. Please wait a moment and tap Refresh OEE."
        detail.contains("CoroutineScope left the composition", ignoreCase = true) ->
            "The screen was refreshed while a request was running. Please tap Refresh OEE again."
        detail.contains("401") || detail.contains("unauthorized", ignoreCase = true) ->
            "Your login session may have expired. Please sign out and sign in again."
        detail.contains("403") || detail.contains("forbidden", ignoreCase = true) ->
            "You do not have permission for this operation. Contact your administrator."
        detail.contains("No active machine mapping", ignoreCase = true) ->
            "No machine is mapped to this operation for the selected date. Ask your administrator to check Machine Allocation."
        else -> fallback
    }
}

private data class ActionItem(val id:Int,val number:String,val description:String,val type:String,val status:String,val priority:String,val due:String,val overdue:Boolean,val whyWhy:Boolean,val completion:Int)
private data class ActionOwnerGroup(val userId:Int?,val name:String,val role:String,val openCount:Int,val overdueCount:Int,val dueTodayCount:Int,val actions:List<ActionItem>)
private data class Masters(val products: List<Choice>, val machines: List<Choice>, val phenomena: List<Choice>)
private data class RejectionTrendPoint(val date: LocalDate, val quantity: Float)

@Composable
private fun ScreenTitle(title: String, subtitle: String? = null) {
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Text(title, color = Navy, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        if (!subtitle.isNullOrBlank()) Text(subtitle, color = Muted, fontSize = 13.sp)
    }
}
@Composable
private fun SectionLabel(title: String, subtitle: String? = null) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(title.uppercase(), color = Navy, fontSize = 13.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.7.sp)
        if (!subtitle.isNullOrBlank()) Text(subtitle, color = Muted, fontSize = 12.sp)
    }
}
@Composable
private fun MetricTile(label: String, value: String, accent: Color, modifier: Modifier = Modifier, compact: Boolean = false) {
    Card(modifier = modifier, shape = RoundedCornerShape(14.dp), colors = CardDefaults.cardColors(containerColor = Color.White),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border), elevation = CardDefaults.cardElevation(1.dp)) {
        Column(Modifier.fillMaxWidth().padding(horizontal = if (compact) 7.dp else 12.dp, vertical = if (compact) 10.dp else 13.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Box(Modifier.width(28.dp).height(3.dp).clip(RoundedCornerShape(3.dp)).background(accent))
            Text(value, color = Navy, fontSize = if (compact) 19.sp else 23.sp, fontWeight = FontWeight.Bold, maxLines = 1, softWrap = false)
            Text(label, color = Muted, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, maxLines = 2)
        }
    }
}
@Composable
private fun EmptyState(title: String, description: String, icon: @Composable () -> Unit = {}) {
    Card(modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp), colors = CardDefaults.cardColors(containerColor = Color.White),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border)) {
        Column(Modifier.fillMaxWidth().padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            icon()
            Text(title, color = Navy, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            Text(description, color = Muted, fontSize = 13.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        }
    }
}
@Composable
private fun StatusPill(label: String, color: Color) {
    Surface(color = color.copy(alpha = 0.10f), shape = RoundedCornerShape(50)) {
        Text(label, color = color, fontSize = 10.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp), maxLines = 1)
    }
}
class MainActivity : ComponentActivity() {
    @OptIn(ExperimentalMaterial3Api::class)
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
            var masters by remember { mutableStateOf<Masters?>(null) }
            var routes by remember { mutableStateOf<List<RouteChoice>>(emptyList()) }
            var date by remember { mutableStateOf(LocalDate.now().toString()) }
            var shift by remember { mutableStateOf("A") }
            var product by remember { mutableStateOf<Choice?>(null) }
            var rejectionTrend by remember { mutableStateOf<List<RejectionTrendPoint>>(emptyList()) }
            var rejectionTrendLoading by remember { mutableStateOf(false) }
            var rejectionTrendError by remember { mutableStateOf<String?>(null) }
            var detection by remember { mutableStateOf<RouteChoice?>(null) }
            var responsible by remember { mutableStateOf<RouteChoice?>(null) }
            var machine by remember { mutableStateOf<Choice?>(null) }
            var phenomenon by remember { mutableStateOf<Choice?>(null) }
            var rejectQty by remember { mutableStateOf("") }
            var reworkQty by remember { mutableStateOf("0") }
            var scrapQty by remember { mutableStateOf("0") }
            var remark by remember { mutableStateOf("") }
            var actionRequired by remember { mutableStateOf(false) }
            var resultMessage by remember { mutableStateOf<String?>(null) }
            var homeTab by remember { mutableStateOf("ACTIONS") }
            var chatConversations by remember { mutableStateOf(JSONArray()) }
            var chatMessages by remember { mutableStateOf(JSONArray()) }
            var chatEmployees by remember { mutableStateOf(JSONArray()) }
            var selectedChatId by remember { mutableStateOf<Int?>(null) }
            var chatDraft by remember { mutableStateOf("") }
            var chatSearch by remember { mutableStateOf("") }
            var chatLoading by remember { mutableStateOf(false) }
            var pendingActions by remember { mutableStateOf<List<ActionItem>>(emptyList()) }
            var pendingActionGroups by remember { mutableStateOf<List<ActionOwnerGroup>>(emptyList()) }
            var selectedOwner by remember { mutableStateOf<ActionOwnerGroup?>(null) }
            var selectedAction by remember { mutableStateOf<ActionItem?>(null) }
            var actionPlan by remember { mutableStateOf<JSONObject?>(null) }
            var followupComment by remember { mutableStateOf("") }
            var actionStatus by remember { mutableStateOf("IN_PROGRESS") }
            var why1 by remember { mutableStateOf("") }
            var why2 by remember { mutableStateOf("") }
            var why3 by remember { mutableStateOf("") }
            var why4 by remember { mutableStateOf("") }
            var why5 by remember { mutableStateOf("") }
            var rootCause by remember { mutableStateOf("") }
            var correctiveAction by remember { mutableStateOf("") }
            var preventiveAction by remember { mutableStateOf("") }
            var verificationMethod by remember { mutableStateOf("") }
            var verificationResult by remember { mutableStateOf("") }
            var evidenceFile by remember { mutableStateOf<File?>(null) }
            var actionAttachments by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
            var actionHistory by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
            var actionHistoryLoading by remember { mutableStateOf(false) }
            var actionHistoryError by remember { mutableStateOf<String?>(null) }
            var whyWhySavedPending by remember { mutableStateOf(false) }
            var evidenceUploadedPending by remember { mutableStateOf(false) }
            var actionUpdateSavedPending by remember { mutableStateOf(false) }
            var pendingFollowupComment by remember { mutableStateOf("") }
            var pendingActionStatus by remember { mutableStateOf("IN_PROGRESS") }
            var submissionStarted by remember { mutableStateOf(false) }
            var oeeDate by remember { mutableStateOf(LocalDate.now().toString()) }
            var showOeeDatePicker by remember { mutableStateOf(false) }
            var oeeShift by remember { mutableStateOf("A") }
            var oeeProduct by remember { mutableStateOf<Choice?>(null) }
            var oeeOperation by remember { mutableStateOf<RouteChoice?>(null) }
            var oeeRoutes by remember { mutableStateOf<List<RouteChoice>>(emptyList()) }
            var oeeMachine by remember { mutableStateOf<Choice?>(null) }
            var oeeMachines by remember { mutableStateOf<List<Choice>>(emptyList()) }
            var oeeSummary by remember { mutableStateOf<JSONObject?>(null) }
            var oeeRecentRecords by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
            var oeeRecentLoading by remember { mutableStateOf(false) }
            var oeeRecentError by remember { mutableStateOf<String?>(null) }
            var oeeError by remember { mutableStateOf<String?>(null) }
            var oeeSuccess by remember { mutableStateOf<String?>(null) }
            var oeeLoading by remember { mutableStateOf(false) }
            var oeeMode by remember { mutableStateOf("SUMMARY") }
            var oeeShiftMinutes by remember { mutableStateOf("480") }
            var oeeBreakMinutes by remember { mutableStateOf("0") }
            var oeeDowntimeMinutes by remember { mutableStateOf("0") }
            var oeeTotalCount by remember { mutableStateOf("0") }
            var oeeGoodCount by remember { mutableStateOf("0") }
            var oeeRejectCount by remember { mutableStateOf("0") }
            var oeeIdealCycleSeconds by remember { mutableStateOf<Double?>(null) }
            var oeeEntryRemarks by remember { mutableStateOf("") }
            var oeeOperators by remember { mutableStateOf<List<Choice>>(emptyList()) }
            var oeeOperatorName by remember { mutableStateOf("") }
            var oeeOperatorId by remember { mutableStateOf<Int?>(null) }
            var oeeOperatorMenu by remember { mutableStateOf(false) }
            var oeeOperatorCreating by remember { mutableStateOf(false) }
            var oeeOperatorError by remember { mutableStateOf<String?>(null) }
            var oeeLossCategories by remember { mutableStateOf<List<Choice>>(emptyList()) }
            var oeeEntryLosses by remember { mutableStateOf(listOf(OeeLossDraft())) }
            var editingLossIndex by remember { mutableStateOf<Int?>(null) }
            var oeeLossCategory by remember { mutableStateOf<Choice?>(null) }
            var oeeLossDuration by remember { mutableStateOf("") }
            var oeeLossQty by remember { mutableStateOf("0") }
            var oeeLossRemark by remember { mutableStateOf("") }
            var oeeSavedLossId by remember { mutableStateOf<Int?>(null) }
            var oeeEditingLossId by remember { mutableStateOf<Int?>(null) }
            var oeeLossCorrectionReason by remember { mutableStateOf("") }
            var oeeEntryId by remember { mutableStateOf<Int?>(null) }
            var oeeLoadingPreviousEntry by remember { mutableStateOf(false) }
            var oeeCorrectionReason by remember { mutableStateOf("") }
            var oeeManagement by remember { mutableStateOf<JSONObject?>(null) }
            var oeeManagementFrom by remember { mutableStateOf(LocalDate.now().withDayOfMonth(1).toString()) }
            var oeeSavedSummary by remember { mutableStateOf<String?>(null) }

            val evidencePicker=rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
                if(uri!=null) {
                    try {
                        val mime=contentResolver.getType(uri).orEmpty()
                        val ext=when(mime){"image/jpeg"->".jpg";"image/png"->".png";"image/webp"->".webp";"application/pdf"->".pdf";"application/vnd.openxmlformats-officedocument.wordprocessingml.document"->".docx";"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"->".xlsx";else->".jpg"}
                        val target=File(cacheDir,"action_evidence_${System.currentTimeMillis()}$ext")
                        contentResolver.openInputStream(uri)?.use{input->target.outputStream().use{input.copyTo(it)}}
                        if(target.exists() && target.length()>0)evidenceFile=target else message="Unable to read selected evidence file."
                    } catch(e:Exception){message=e.message ?: "Unable to select evidence."}
                }
            }


            val defectPhotos = remember { mutableStateListOf<File>() }
            var pendingPhotoFile by remember { mutableStateOf<File?>(null) }
            var savedRejectionId by remember { mutableStateOf<Int?>(null) }
            val cameraLauncher = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { captured ->
                val photo = pendingPhotoFile
                if (captured && photo != null && photo.exists() && photo.length() > 0) {
                    if (defectPhotos.size < 5) defectPhotos.add(photo) else photo.delete()
                } else photo?.delete()
                pendingPhotoFile = null
            }
            val scope = this@MainActivity.lifecycleScope
            val drawerState = rememberDrawerState(DrawerValue.Closed)
            var showLogoutConfirm by remember { mutableStateOf(false) }

            fun refreshPendingActions(auth:String) {
                scope.launch {
                    try {
                        if (account?.role?.uppercase() in listOf("ADMIN", "MANAGEMENT")) {
                            pendingActionGroups = withContext(Dispatchers.IO) { ApiClient.loadPendingActionGroups(auth) }
                            pendingActions = emptyList()
                        } else {
                            pendingActions = withContext(Dispatchers.IO) { ApiClient.loadPendingActions(auth) }
                            pendingActionGroups = emptyList()
                        }
                    } catch(e:Exception){ message="Unable to load pending actions: ${e.message}" }
                }
            }
            fun openAction(item:ActionItem,auth:String) {
                scope.launch {
                    busy=true; message="Loading action…"; selectedAction=item
                    try {
                        val data=withContext(Dispatchers.IO){ApiClient.loadActionPlan(item.id,auth)}
                        actionPlan=data.optJSONObject("plan")
                        val attachments=data.optJSONArray("attachments") ?: JSONArray()
                        actionAttachments=(0 until attachments.length()).map{attachments.getJSONObject(it)}
                        actionHistory=emptyList();actionHistoryError=null
                        whyWhySavedPending=false;evidenceUploadedPending=false;actionUpdateSavedPending=false
                        pendingFollowupComment="";pendingActionStatus=item.status;submissionStarted=false
                        val p=actionPlan
                        why1=p?.optString("why1").orEmpty().takeUnless{it=="null"}.orEmpty()
                        why2=p?.optString("why2").orEmpty().takeUnless{it=="null"}.orEmpty()
                        why3=p?.optString("why3").orEmpty().takeUnless{it=="null"}.orEmpty()
                        why4=p?.optString("why4").orEmpty().takeUnless{it=="null"}.orEmpty()
                        why5=p?.optString("why5").orEmpty().takeUnless{it=="null"}.orEmpty()
                        rootCause=p?.optString("root_cause").orEmpty().takeUnless{it=="null"}.orEmpty()
                        correctiveAction=p?.optString("corrective_action").orEmpty().takeUnless{it=="null"}.orEmpty()
                        preventiveAction=p?.optString("preventive_action").orEmpty().takeUnless{it=="null"}.orEmpty()
                        verificationMethod=p?.optString("verification_method").orEmpty().takeUnless{it=="null"}.orEmpty()
                        verificationResult=p?.optString("verification_result").orEmpty().takeUnless{it=="null"}.orEmpty()
                        followupComment=""
                        actionStatus=item.status
                        homeTab="DETAIL"
                        message="Action details loaded."
                    } catch(e:Exception){selectedAction=null;message=e.message ?: "Unable to load action."}
                    finally{busy=false}
                }
            }

            fun loadOeeScope(auth: String, selectedProduct: Choice? = oeeProduct) {
                if (selectedProduct == null) { oeeError = "Select a product first."; return }
                scope.launch {
                    oeeLoading = true; oeeError = null; oeeSummary = null
                    try {
                        val routeCandidates = withContext(Dispatchers.IO) { ApiClient.loadRoutes(selectedProduct.id, oeeDate, auth) }
                        val mapped = withContext(Dispatchers.IO) {
                            routeCandidates.mapNotNull { operation ->
                                val machines = ApiClient.loadOeeMachines(operation.id, oeeDate, auth)
                                if (machines.isNotEmpty()) operation to machines else null
                            }
                        }
                        oeeRoutes = mapped.map { it.first }
                        oeeOperation = mapped.firstOrNull()?.first
                        oeeMachines = mapped.firstOrNull()?.second.orEmpty()
                        oeeMachine = oeeMachines.firstOrNull()
                        if (oeeRoutes.isEmpty()) {
                            oeeMachine = null
                            oeeError = "No operations with active machine mapping are available for this part and date."
                        }
                    } catch (e: Exception) { oeeError = userFriendlyOeeError(e, "Could not load operations and machines. Check your connection, then tap Refresh OEE.") }
                    finally { oeeLoading = false }
                }
                scope.launch {
                    try {
                        val categories = withContext(Dispatchers.IO) { ApiClient.loadOeeLossCategories(auth) }
                        oeeLossCategories = categories
                        oeeLossCategory = categories.firstOrNull()
                    } catch (e: Exception) { oeeError = e.message ?: "Unable to load loss categories." }
                }
            }
            fun refreshOee(auth: String) {
                val selectedProduct = oeeProduct; val selectedOperation = oeeOperation; val selectedMachine = oeeMachine
                if (selectedProduct == null || selectedOperation == null || selectedMachine == null) { oeeError = "Select a part, applicable operation and machine first."; return }
                scope.launch {
                    oeeLoading = true; oeeError = null
                    try {
                        oeeSummary = withContext(Dispatchers.IO) { ApiClient.loadOeeSummary(selectedMachine.id, oeeDate, oeeShift, selectedProduct.id, selectedOperation.id, auth) }
                    } catch (e: Exception) { oeeError = userFriendlyOeeError(e, "Could not refresh OEE. Check your connection and try again.") }
                    finally { oeeLoading = false }
                }
            }

            fun editOeeEntry(entryDate: String, entryShift: String, expectedEntryId: Int) {
                val auth = token
                val product = oeeProduct
                val operation = oeeOperation
                val machine = oeeMachine
                if (auth == null || product == null || operation == null || machine == null) {
                    oeeError = "Select product, operation and machine before editing."
                    return
                }
                oeeDate = entryDate
                oeeShift = entryShift
                oeeLoadingPreviousEntry = true
                oeeMode = "ENTRY"
                scope.launch {
                    oeeLoading = true
                    oeeError = null
                    oeeSuccess = null
                    try {
                        val context = withContext(Dispatchers.IO) {
                            ApiClient.loadOeeEntryContext(product.id, operation.id, machine.id, entryDate, entryShift, auth)
                        }
                        val entry = context.optJSONObject("existing_entry")
                        if (entry == null || entry.optInt("id") != expectedEntryId) {
                            throw IllegalStateException("The selected production record is no longer available in this scope. Refresh Summary and try again.")
                        }
                        oeeEntryId = entry.optInt("id")
                        if (oeeOperators.isEmpty()) {
                            oeeOperators = withContext(Dispatchers.IO) { ApiClient.loadOeeOperators(auth) }
                        }
                        oeeCorrectionReason = ""
                        oeeOperatorName = entry.optString("operator_name").takeIf { it.isNotBlank() && it != "null" }.orEmpty()
                        oeeOperatorId = oeeOperators.firstOrNull { it.label.equals(oeeOperatorName, ignoreCase = true) }?.id
                        if (oeeOperatorId == null) throw IllegalStateException("Could not match the saved operator to Personnel Master. Refresh and try again.")
                        oeeShiftMinutes = entry.optDouble("shift_duration_min", 480.0).toString()
                        oeeBreakMinutes = entry.optDouble("planned_break_min", 0.0).toString()
                        oeeGoodCount = entry.optDouble("good_count", 0.0).toString()
                        oeeRejectCount = entry.optDouble("reject_count", 0.0).toString()
                        oeeEntryRemarks = entry.optString("remarks").takeUnless { it == "null" }.orEmpty()
                        val savedLosses = context.optJSONArray("existing_losses") ?: JSONArray()
                        val loadedLosses = (0 until savedLosses.length()).map { index ->
                            val loss = savedLosses.getJSONObject(index)
                            OeeLossDraft(
                                categoryId = loss.optInt("loss_category_id").takeIf { it > 0 },
                                duration = loss.optDouble("duration_min").toString(),
                                qty = loss.optDouble("qty_loss").toString(),
                                remark = loss.optString("remark"),
                                saved = true,
                                id = loss.optInt("id").takeIf { it > 0 },
                                category = loss.optString("category"),
                                component = loss.optString("component"),
                                startTime = loss.optString("start_time").takeUnless { it == "null" }.orEmpty(),
                                endTime = loss.optString("end_time").takeUnless { it == "null" }.orEmpty()
                            )
                        }
                        oeeEntryLosses = loadedLosses + listOf(OeeLossDraft())
                    } catch (e: Exception) {
                        oeeEntryId = null
                        oeeError = e.message ?: "Unable to load the selected production record."
                    } finally {
                        oeeLoadingPreviousEntry = false
                        oeeLoading = false
                    }
                }
            }

            LaunchedEffect(homeTab, token, oeeProduct?.id, oeeOperation?.id, oeeMachine?.id, oeeDate, oeeShift) {
                val auth = token
                val productId = oeeProduct?.id
                val operationId = oeeOperation?.id
                val machineId = oeeMachine?.id
                if (homeTab == "OEE" && auth != null && productId != null && operationId != null && machineId != null) {
                    oeeRecentLoading = true
                    oeeRecentError = null
                    try {
                        val endDate = LocalDate.parse(oeeDate)
                        val startDate = endDate.minusDays(6)
                        val response = withContext(Dispatchers.IO) {
                            ApiClient.loadOeeRecentRecords(startDate.toString(), endDate.toString(), oeeShift, machineId, productId, operationId, auth)
                        }
                        val rows = response.optJSONArray("records") ?: JSONArray()
                        oeeRecentRecords = (0 until rows.length()).map { rows.getJSONObject(it) }
                    } catch (e: Exception) {
                        oeeRecentRecords = emptyList()
                        oeeRecentError = e.message ?: "Unable to load recent OEE records."
                    } finally {
                        oeeRecentLoading = false
                    }
                } else {
                    oeeRecentRecords = emptyList()
                    oeeRecentError = null
                }
            }

            LaunchedEffect(homeTab, token, oeeProduct?.id, oeeOperation?.id, oeeMachine?.id, oeeDate) {
                val auth = token
                val p = oeeProduct
                val op = oeeOperation
                val m = oeeMachine
                if (homeTab == "OEE" && auth != null && p != null && op != null && m != null) {
                    oeeIdealCycleSeconds = null
                    try {
                        val context = withContext(Dispatchers.IO) {
                            ApiClient.loadOeeEntryContext(p.id, op.id, m.id, oeeDate, oeeShift, auth)
                        }
                        oeeIdealCycleSeconds = context.optDouble("ideal_cycle_time_sec").takeIf { context.has("ideal_cycle_time_sec") && !context.isNull("ideal_cycle_time_sec") && it > 0.0 }
                    } catch (_: Exception) {
                        oeeIdealCycleSeconds = null
                    }
                } else {
                    oeeIdealCycleSeconds = null
                }
            }

            LaunchedEffect(homeTab, oeeMode, token, oeeProduct?.id, oeeOperation?.id, oeeMachine?.id, oeeDate, oeeShift) {
                val auth = token
                val product = oeeProduct
                val operation = oeeOperation
                val machine = oeeMachine
                if (homeTab == "OEE" && oeeMode == "ENTRY" && auth != null &&
                    product != null && operation != null && machine != null) {
                    // Capture the explicit edit intent before any suspending master-data calls.
                    // The edit loader may finish while this effect is still loading categories/operators.
                    val preserveSelectedRecord = oeeLoadingPreviousEntry
                    oeeLoading = true
                    try {
                        if (oeeLossCategories.isEmpty()) {
                            oeeLossCategories = withContext(Dispatchers.IO) { ApiClient.loadOeeLossCategories(auth) }
                        }
                        if (oeeOperators.isEmpty()) {
                            oeeOperators = withContext(Dispatchers.IO) { ApiClient.loadOeeOperators(auth) }
                        }
                        // ENTRY always opens as a new production record unless the user
                        // explicitly selected a record to correct. Preserve that intent
                        // across the asynchronous master-data loading above.
                        if (!preserveSelectedRecord) {
                            // Every fresh entry starts with zero planned breaks.
                            oeeEntryId = null
                            oeeBreakMinutes = "0"
                            oeeCorrectionReason = ""
                            oeeShiftMinutes = "480"
                            oeeGoodCount = "0"
                            oeeRejectCount = "0"
                            oeeEntryRemarks = ""
                            oeeEntryLosses = listOf(OeeLossDraft())
                        }
                        oeeError = null
                    } catch (e: Exception) {
                        oeeError = e.message ?: "Unable to load production entry."
                    } finally {
                        oeeLoading = false
                    }
                }
            }

            LaunchedEffect(homeTab, token, oeeProduct?.id, oeeOperation?.id, oeeMachine?.id) {
                val auth = token
                if (homeTab == "OEE" && auth != null) {
                    oeeLoading = true
                    oeeError = null
                    try {
                        val today = LocalDate.now()
                        val monthStart = today.withDayOfMonth(1)
                        oeeManagement = withContext(Dispatchers.IO) {
                            ApiClient.loadOeeManagement(
                                monthStart.toString(), today.toString(), auth,
                                oeeProduct?.id, oeeOperation?.id, oeeMachine?.id
                            )
                        }
                    } catch (e: Exception) {
                        oeeError = e.message ?: "Unable to load current-month OEE."
                        oeeManagement = null
                    } finally {
                        oeeLoading = false
                    }
                }
            }

            fun resetRejectionForm() {
                date = LocalDate.now().toString()
                shift = "A"
                product = null
                rejectionTrend = emptyList()
                rejectionTrendError = null
                detection = null
                responsible = null
                machine = null
                phenomenon = null
                rejectQty = ""
                reworkQty = "0"
                scrapQty = "0"
                remark = ""
                actionRequired = false
                routes = emptyList()
            }

            fun refreshMasters(auth: String) {
                scope.launch {
                    busy=true; message="Loading production masters…"
                    try {
                        val loaded=withContext(Dispatchers.IO) { ApiClient.loadMasters(auth) }
                        masters=loaded
                        message="Connected. Production masters loaded."
                    } catch(e:Exception) { message=e.message ?: "Unable to load masters." }
                    finally { busy=false }
                }
            }
            fun refreshRejectionTrend(productId: Int, auth: String) {
                val today = LocalDate.now()
                val fromDate = today.withDayOfMonth(1)
                val toDate = today.withDayOfMonth(today.lengthOfMonth())
                scope.launch {
                    rejectionTrendLoading = true
                    rejectionTrendError = null
                    rejectionTrend = emptyList()
                    try {
                        rejectionTrend = withContext(Dispatchers.IO) {
                            ApiClient.loadRejectionTrend(productId, fromDate, toDate, auth)
                        }
                    } catch (e: Exception) {
                        rejectionTrendError = e.message ?: "Unable to load monthly rejection quantities."
                    } finally {
                        rejectionTrendLoading = false
                    }
                }
            }

            fun refreshRoutes(productId: Int, onDate: String, auth: String) {
                scope.launch {
                    detection=null; responsible=null; routes=emptyList()
                    try {
                        val loaded=withContext(Dispatchers.IO) { ApiClient.loadRoutes(productId,onDate,auth) }
                        routes=loaded
                        if (loaded.isEmpty()) message="No active route found for this product and date."
                    } catch(e:Exception) { message=e.message ?: "Unable to load product route." }
                }
            }

            LaunchedEffect(Unit) {
                val saved=withContext(Dispatchers.IO) { sessionStore.read() }
                if (!saved.isNullOrBlank()) {
                    busy=true
                    try {
                        val current=withContext(Dispatchers.IO) { ApiClient.currentAccount(saved) }
                        token=saved; account=current; refreshMasters(saved); refreshPendingActions(saved)
                        message="Connected to Production Review."
                    } catch(_:Exception) {
                        withContext(Dispatchers.IO) { sessionStore.clear() }
                        message="Your saved session has expired. Please sign in again."
                    } finally { busy=false }
                }
            }

            fun refreshChatConversations(auth: String) {
                chatLoading = true
                scope.launch {
                    try { chatConversations = withContext(Dispatchers.IO) { ApiClient.loadChatConversations(auth) } }
                    catch (e: Exception) { message = "Chat: ${e.message}" }
                    finally { chatLoading = false }
                }
            }
            fun refreshChatMessages(auth: String, conversationId: Int) {
                scope.launch {
                    try { chatMessages = withContext(Dispatchers.IO) { ApiClient.loadChatMessages(conversationId, auth) } }
                    catch (e: Exception) { message = "Chat: ${e.message}" }
                }
            }
            fun searchChatEmployees(auth: String) {
                scope.launch {
                    try { chatEmployees = withContext(Dispatchers.IO) { ApiClient.loadChatEmployees(chatSearch, auth) } }
                    catch (e: Exception) { message = "Chat: ${e.message}" }
                }
            }
            val normalizedRole = account?.role?.uppercase().orEmpty()
            val isAdminOrManagement = normalizedRole in listOf("ADMIN", "MANAGEMENT")
            val isQualityRole = normalizedRole.contains("QUALITY") || normalizedRole.contains("QA")
            val isProductionRole = normalizedRole.contains("PRODUCTION") || normalizedRole.contains("PROD")
            val bottomDestinations = buildList {
                add("ACTIONS")
                if (isQualityRole || isAdminOrManagement) add("REJECTION")
                if (isProductionRole || isAdminOrManagement) add("OEE")
                if (isQualityRole && isProductionRole) { /* both operational shortcuts are permitted */ }
                add("MORE")
            }.distinct().take(4)

            MaterialTheme(
                colorScheme = lightColorScheme(primary = Teal, onPrimary = Color.White, secondary = Navy, background = Canvas, surface = Color.White, error = Danger),
                typography = Typography(
                    bodyLarge = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp, color = Navy),
                    bodyMedium = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp, color = Navy),
                    bodySmall = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp, color = Muted),
                    titleLarge = MaterialTheme.typography.titleLarge.copy(fontSize = 22.sp, fontWeight = FontWeight.Bold),
                    titleMedium = MaterialTheme.typography.titleMedium.copy(fontSize = 18.sp, fontWeight = FontWeight.Bold)
                )
            ) {
                ModalNavigationDrawer(
                    drawerState = drawerState,
                    gesturesEnabled = account != null,
                    drawerContent = {
                        ModalDrawerSheet(
                            modifier=Modifier.fillMaxHeight().fillMaxWidth(0.60f),
                            drawerContainerColor=Color(0xFFF1F4F7),
                            drawerTonalElevation=4.dp
                        ) {
                            Column(Modifier.fillMaxSize()) {
                                Column(
                                    Modifier.fillMaxWidth().background(Brush.verticalGradient(listOf(Color(0xFF173B5E),Color(0xFF071D33)))).padding(horizontal=10.dp,vertical=18.dp),
                                    horizontalAlignment=Alignment.Start,
                                    verticalArrangement=Arrangement.spacedBy(5.dp)
                                ) {
                                    Box(Modifier.size(42.dp).clip(RoundedCornerShape(14.dp)).background(Color(0xFF0B6BA8)),contentAlignment=Alignment.Center) {
                                        Icon(Icons.Filled.Settings,contentDescription="Machine shop",tint=Color.White,modifier=Modifier.size(30.dp))
                                    }
                                    Text("MACHINE SHOP",color=Color.White,fontSize=14.sp,fontWeight=FontWeight.ExtraBold,letterSpacing=0.5.sp,maxLines=1)
                                    Text("OPERATIONS",color=Color(0xFFFFA726),fontSize=12.sp,fontWeight=FontWeight.Bold,letterSpacing=1.sp,maxLines=1)
                                    Divider(color=Color(0xFFFFA726),thickness=2.dp,modifier=Modifier.width(62.dp).padding(top=3.dp))
                                    Text(account?.fullName?.ifBlank { account?.username.orEmpty() }.orEmpty(),color=Color.White,fontSize=13.sp,fontWeight=FontWeight.SemiBold,maxLines=2)
                                    Text(account?.role.orEmpty(),color=Color(0xFFB9D5E5),fontSize=11.sp,maxLines=1)
                                }
                                Column(Modifier.weight(1f).fillMaxWidth().padding(horizontal=5.dp,vertical=8.dp),verticalArrangement=Arrangement.spacedBy(3.dp)) {
                                    NavigationDrawerItem(modifier=Modifier.fillMaxWidth(),label={Text("Actions",fontSize=14.sp,fontWeight=FontWeight.SemiBold,maxLines=1)},selected=homeTab=="ACTIONS" || homeTab=="USER_ACTIONS" || homeTab=="DETAIL",icon={Icon(Icons.Filled.Assignment,contentDescription=null,modifier=Modifier.size(22.dp))},onClick={scope.launch { drawerState.close(); homeTab="ACTIONS"; selectedOwner=null; token?.let{refreshPendingActions(it)} }},colors=NavigationDrawerItemDefaults.colors(selectedContainerColor=Color(0xFFD7E9FA),selectedIconColor=Navy,selectedTextColor=Navy))
                                    if (isQualityRole || isAdminOrManagement) NavigationDrawerItem(modifier=Modifier.fillMaxWidth(),label={Text("Rejection",fontSize=14.sp,fontWeight=FontWeight.SemiBold,maxLines=1)},selected=homeTab=="REJECTION",icon={Icon(Icons.Filled.AssignmentLate,contentDescription=null,modifier=Modifier.size(22.dp))},onClick={scope.launch { drawerState.close(); homeTab="REJECTION" }},colors=NavigationDrawerItemDefaults.colors(selectedContainerColor=Color(0xFFD7E9FA),selectedIconColor=Navy,selectedTextColor=Navy))
                                    if (isProductionRole || isAdminOrManagement) NavigationDrawerItem(modifier=Modifier.fillMaxWidth(),label={Text("OEE",fontSize=14.sp,fontWeight=FontWeight.SemiBold,maxLines=1)},selected=homeTab=="OEE",icon={Icon(Icons.Filled.Speed,contentDescription=null,modifier=Modifier.size(22.dp))},onClick={scope.launch { drawerState.close(); homeTab="OEE" }},colors=NavigationDrawerItemDefaults.colors(selectedContainerColor=Color(0xFFD7E9FA),selectedIconColor=Navy,selectedTextColor=Navy))
                                    NavigationDrawerItem(modifier=Modifier.fillMaxWidth(),label={Text("Chat",fontSize=14.sp,fontWeight=FontWeight.SemiBold,maxLines=1)},selected=homeTab=="CHAT",icon={Text("✉",fontSize=19.sp,color=Teal)},onClick={scope.launch { drawerState.close(); homeTab="CHAT"; token?.let{refreshChatConversations(it)}; chatSearch=""; chatEmployees=JSONArray() }},colors=NavigationDrawerItemDefaults.colors(selectedContainerColor=Color(0xFFD7E9FA),selectedIconColor=Navy,selectedTextColor=Navy))
                                    NavigationDrawerItem(modifier=Modifier.fillMaxWidth(),label={Text("History",fontSize=14.sp,fontWeight=FontWeight.SemiBold,maxLines=1)},selected=homeTab=="HISTORY",icon={Icon(Icons.Filled.History,contentDescription=null,modifier=Modifier.size(22.dp))},onClick={scope.launch { drawerState.close(); homeTab="HISTORY" }},colors=NavigationDrawerItemDefaults.colors(selectedContainerColor=Color(0xFFD7E9FA),selectedIconColor=Navy,selectedTextColor=Navy))
                                }
                                Divider(color=Color(0xFFCBD5DF))
                                Column(Modifier.fillMaxWidth().padding(horizontal=5.dp,vertical=6.dp),verticalArrangement=Arrangement.spacedBy(3.dp)) {
                                    NavigationDrawerItem(modifier=Modifier.fillMaxWidth().heightIn(min=56.dp),label={Text("Account",fontSize=14.sp,fontWeight=FontWeight.SemiBold,maxLines=1)},selected=homeTab=="ACCOUNT",icon={Icon(Icons.Filled.Person,contentDescription=null,modifier=Modifier.size(22.dp))},onClick={scope.launch { drawerState.close(); homeTab="ACCOUNT" }})
                                    NavigationDrawerItem(modifier=Modifier.fillMaxWidth().heightIn(min=56.dp),label={Text("Logout",fontSize=14.sp,fontWeight=FontWeight.Bold,maxLines=1)},selected=false,icon={Icon(Icons.Filled.Logout,contentDescription=null,tint=Color(0xFFB3261E),modifier=Modifier.size(22.dp))},onClick={scope.launch { drawerState.close(); showLogoutConfirm=true }},colors=NavigationDrawerItemDefaults.colors(unselectedTextColor=Color(0xFFB3261E),unselectedIconColor=Color(0xFFB3261E)))
                                }
                            }
                        }
                    }
                ) {
                Surface(Modifier.fillMaxSize(),color=Canvas) {
                    Column(Modifier.fillMaxSize()) {
                    Column(Modifier.weight(1f).fillMaxWidth()) {
                        Row(Modifier.fillMaxWidth().background(Brush.horizontalGradient(listOf(Color(0xFF102A43), Navy, Color(0xFF1D4568)))).padding(horizontal=12.dp,vertical=12.dp), verticalAlignment=Alignment.CenterVertically) {
                            if (account != null) IconButton(onClick={scope.launch { drawerState.open() }}) { Icon(Icons.Filled.Menu, contentDescription="Open navigation", tint=Color.White) }
                            Column(Modifier.weight(1f)) {
                                Text("PRODUCTION REVIEW",color=Color(0xFFB9D5E5),fontSize=10.sp,fontWeight=FontWeight.Bold,letterSpacing=1.2.sp)
                                Text(if (account == null) "Mobile Operations" else when(homeTab) { "ACTIONS"->"Pending Actions"; "USER_ACTIONS"->"User Actions"; "DETAIL"->"Action Details"; "REJECTION"->"Rejection Entry"; "OEE"->"OEE"; "HISTORY"->"Action History"; "CHAT"->"Chat"; "ACCOUNT"->"Account"; else->"Mobile Operations" },color=Color.White,fontSize=19.sp,fontWeight=FontWeight.Bold)
                            }
                        }
                        if (homeTab == "CHAT") {
                            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement=Arrangement.spacedBy(10.dp)) {
                                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically) {
                                    ScreenTitle("Employee Chat","Message any employee or continue a conversation")
                                    TextButton(onClick={token?.let{refreshChatConversations(it)}}){Text("REFRESH",color=Teal)}
                                }
                                Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(13.dp),colors=CardDefaults.cardColors(containerColor=Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border)) {
                                    Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
                                        Text("Start a new conversation",color=Navy,fontWeight=FontWeight.Bold,fontSize=14.sp)
                                        OutlinedTextField(value=chatSearch,onValueChange={chatSearch=it},modifier=Modifier.fillMaxWidth(),singleLine=true,label={Text("Search employee name or username")})
                                        Button(onClick={token?.let{searchChatEmployees(it)}},modifier=Modifier.fillMaxWidth(),colors=ButtonDefaults.buttonColors(containerColor=Teal)){Text("SEARCH EMPLOYEES")}
                                        for(i in 0 until chatEmployees.length()) {
                                            val employee=chatEmployees.optJSONObject(i) ?: continue
                                            Row(Modifier.fillMaxWidth().clickable {
                                                val auth=token
                                                if(auth!=null) scope.launch {
                                                    try {
                                                        val conversation=withContext(Dispatchers.IO){ApiClient.createDirectChat(employee.optInt("id"),auth)}
                                                        selectedChatId=conversation.optInt("id")
                                                        refreshChatConversations(auth)
                                                        refreshChatMessages(auth,selectedChatId!!)
                                                        chatEmployees=JSONArray()
                                                        chatSearch=""
                                                    } catch(e:Exception){message="Unable to start chat: ${e.message}"}
                                                }
                                            }.padding(vertical=7.dp),verticalAlignment=Alignment.CenterVertically) {
                                                Column(Modifier.weight(1f)) {
                                                    Text(employee.optString("full_name"),color=Navy,fontWeight=FontWeight.SemiBold,fontSize=13.sp)
                                                    Text(employee.optString("username")+" • "+employee.optString("role"),color=Muted,fontSize=11.sp)
                                                }
                                                Text("MESSAGE →",color=Teal,fontWeight=FontWeight.Bold,fontSize=10.sp)
                                            }
                                            Divider(color=Border)
                                        }
                                    }
                                }
                                Text("CONVERSATIONS",color=Navy,fontWeight=FontWeight.Bold,fontSize=12.sp,letterSpacing=0.8.sp)
                                if(chatConversations.length()==0) EmptyState("No conversations yet","Search for an employee above to start chatting.")
                                for(i in 0 until chatConversations.length()) {
                                    val conversation=chatConversations.optJSONObject(i) ?: continue
                                    val conversationId=conversation.optInt("id")
                                    val title=conversation.optString("title").ifBlank {
                                        val participants=conversation.optJSONArray("participants") ?: JSONArray()
                                        (0 until participants.length()).mapNotNull{participants.optJSONObject(it)}
                                            .filter{it.optInt("id")!=account?.let{_->-1}}
                                            .joinToString(", "){it.optString("full_name")}
                                    }
                                    Card(Modifier.fillMaxWidth().clickable {
                                        selectedChatId=conversationId
                                        token?.let{refreshChatMessages(it,conversationId)}
                                    },shape=RoundedCornerShape(12.dp),colors=CardDefaults.cardColors(containerColor=if(selectedChatId==conversationId)Color(0xFFEAF5F5) else Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border)) {
                                        Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(4.dp)) {
                                            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
                                                Text(title.ifBlank{"Conversation"},color=Navy,fontWeight=FontWeight.Bold,fontSize=13.sp)
                                                if(conversation.optInt("unread_count")>0) StatusPill("${conversation.optInt("unread_count")} NEW",Teal)
                                            }
                                            Text(conversation.optJSONObject("last_message")?.optString("body")?.ifBlank{"No messages yet"} ?: "No messages yet",color=Muted,fontSize=11.sp,maxLines=1)
                                        }
                                    }
                                }
                                if(selectedChatId!=null) {
                                    Divider(color=Border,thickness=1.dp)
                                    Text("MESSAGES",color=Navy,fontWeight=FontWeight.Bold,fontSize=12.sp)
                                    for(i in 0 until chatMessages.length()) {
                                        val msg=chatMessages.optJSONObject(i) ?: continue
                                        Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(10.dp),colors=CardDefaults.cardColors(containerColor=if(msg.optInt("sender_id")==account?.let{0} )Color(0xFFEAF5F5) else Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border)) {
                                            Column(Modifier.padding(10.dp)) {
                                                Text(msg.optString("sender_name"),color=Teal,fontSize=10.sp,fontWeight=FontWeight.Bold)
                                                Text(msg.optString("body"),color=Navy,fontSize=13.sp)
                                            }
                                        }
                                    }
                                    OutlinedTextField(value=chatDraft,onValueChange={chatDraft=it},modifier=Modifier.fillMaxWidth(),label={Text("Write a message")})
                                    Button(onClick={
                                        val auth=token;val id=selectedChatId;val body=chatDraft.trim()
                                        if(auth!=null&&id!=null&&body.isNotBlank())scope.launch{
                                            chatLoading=true
                                            try{withContext(Dispatchers.IO){ApiClient.sendChatMessage(id,body,auth)};chatDraft="";refreshChatMessages(auth,id);refreshChatConversations(auth)}
                                            catch(e:Exception){message="Message not sent: ${e.message}"}
                                            finally{chatLoading=false}
                                        }
                                    },enabled=chatDraft.isNotBlank()&&!chatLoading,modifier=Modifier.fillMaxWidth(),colors=ButtonDefaults.buttonColors(containerColor=Teal)){Text(if(chatLoading)"SENDING…" else "SEND MESSAGE")}
                                }
                            }
                        } else if (homeTab == "OEE") {
                            val monthOee = oeeManagement?.optJSONObject("overall")
                            val headerGood=oeeGoodCount.toDoubleOrNull()?.coerceAtLeast(0.0)?:0.0
                            val headerReject=oeeRejectCount.toDoubleOrNull()?.coerceAtLeast(0.0)?:0.0
                            val headerTotal=headerGood+headerReject
                            val headerDowntime=oeeEntryLosses.filter{it.categoryId!=null&&(isAvailabilityOeeLoss(it,oeeLossCategories))}.sumOf{it.duration.toDoubleOrNull()?:0.0}
                            val headerPlanned=((oeeShiftMinutes.toDoubleOrNull()?:0.0)-(oeeBreakMinutes.toDoubleOrNull()?:0.0)).coerceAtLeast(0.0)
                            val headerRun=(headerPlanned-headerDowntime).coerceAtLeast(0.0)
                            val headerAvailability=if(headerPlanned>0)headerRun/headerPlanned else 0.0
                            val headerPerfRaw=if(headerRun>0)((oeeIdealCycleSeconds?:0.0)*headerTotal/60.0)/headerRun else 0.0
                            val headerPerformance=headerPerfRaw.coerceIn(0.0,1.0)
                            val headerQuality=if(headerTotal>0)headerGood/headerTotal else 0.0
                            val showLiveHeader=oeeMode=="ENTRY"&&oeeProduct!=null&&headerTotal>0
                            val headerOee=if(showLiveHeader&&oeeIdealCycleSeconds!=null)headerAvailability*headerPerformance*headerQuality else monthOee?.optDouble("oee_reported")?:0.0
                            val headerAvail=if(showLiveHeader)headerAvailability else monthOee?.optDouble("availability")?:0.0
                            val headerPerf=if(showLiveHeader)headerPerformance else monthOee?.optDouble("performance_raw")?:0.0
                            val headerQual=if(showLiveHeader)headerQuality else monthOee?.optDouble("quality")?:0.0
                            Card(
                                Modifier.fillMaxWidth().padding(horizontal=12.dp, vertical=6.dp),
                                shape=RoundedCornerShape(15.dp),
                                colors=CardDefaults.cardColors(containerColor=Navy),
                                elevation=CardDefaults.cardElevation(defaultElevation=2.dp)
                            ) {
                                Row(
                                    Modifier.fillMaxWidth().background(Brush.horizontalGradient(listOf(Color(0xFF193B5B),Color(0xFF087F8C)))).padding(horizontal=14.dp, vertical=10.dp),
                                    verticalAlignment=Alignment.CenterVertically,
                                    horizontalArrangement=Arrangement.spacedBy(12.dp)
                                ) {
                                    Column(Modifier.weight(1f), verticalArrangement=Arrangement.spacedBy(2.dp)) {
                                        Text(if(showLiveHeader)"LIVE ENTRY OEE" else "CURRENT-MONTH OEE",color=Color(0xFFD4E7F1),fontSize=12.sp,fontWeight=FontWeight.Bold,letterSpacing=0.8.sp)
                                        Text(if(showLiveHeader&&oeeIdealCycleSeconds==null)"—" else if(showLiveHeader||monthOee!=null)"${"%.1f".format(headerOee*100)}%" else "—",color=Color.White,fontSize=34.sp,fontWeight=FontWeight.ExtraBold)
                                    }
                                    Column(Modifier.weight(2f),verticalArrangement=Arrangement.spacedBy(5.dp)) {
                                        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(5.dp)) {
                                            listOf("AVAIL" to headerAvail,"PERF" to headerPerf,"QUAL" to headerQual).forEach { (label,value) ->
                                                Column(Modifier.weight(1f).clip(RoundedCornerShape(8.dp)).background(Color(0x22FFFFFF)).padding(horizontal=6.dp,vertical=5.dp)) {
                                                    Text(if(if(showLiveHeader)label!="PERF"||oeeIdealCycleSeconds!=null else monthOee!=null)"${"%.1f".format(value*100)}%" else "—",color=Color.White,fontSize=16.sp,fontWeight=FontWeight.ExtraBold)
                                                    Text(label,color=Color(0xFFD4E7F1),fontSize=10.sp,fontWeight=FontWeight.Bold)
                                                }
                                            }
                                        }
                                        if(showLiveHeader) {
                                            val livePulse = rememberInfiniteTransition(label="liveQuantityPulse")
                                            val liveAlpha by livePulse.animateFloat(
                                                initialValue=0.58f,
                                                targetValue=1.0f,
                                                animationSpec=infiniteRepeatable(
                                                    animation=tween(durationMillis=850, easing=FastOutSlowInEasing),
                                                    repeatMode=RepeatMode.Reverse
                                                ),
                                                label="liveQuantityAlpha"
                                            )
                                            Row(
                                                modifier=Modifier
                                                    .clip(RoundedCornerShape(20.dp))
                                                    .background(Color(0x3348E0B4))
                                                    .border(1.dp,Color(0x8848E0B4),RoundedCornerShape(20.dp))
                                                    .padding(horizontal=10.dp,vertical=5.dp),
                                                verticalAlignment=Alignment.CenterVertically,
                                                horizontalArrangement=Arrangement.spacedBy(6.dp)
                                            ) {
                                                Box(Modifier.size(7.dp).clip(CircleShape).background(Color(0xFFFF3B30).copy(alpha=liveAlpha)))
                                                Text(
                                                    if(oeeIdealCycleSeconds==null) "LIVE • CYCLE TIME NEEDED" else "LIVE • ${headerTotal.toInt()} PCS",
                                                    color=Color(0xFF8BFFD0).copy(alpha=liveAlpha),
                                                    fontSize=12.sp,
                                                    fontWeight=FontWeight.ExtraBold,
                                                    letterSpacing=0.35.sp,
                                                    maxLines=1
                                                )
                                            }
                                        } else {
                                            Text("Part: ${oeeProduct?.label ?: "Select a part"}",color=Color(0xFFD4E7F1),fontSize=11.sp,maxLines=1)
                                        }
                                    }
                                }
                            }
                        }
                        Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal=16.dp, vertical=14.dp),verticalArrangement=Arrangement.spacedBy(14.dp)) {
                            if (account == null) {
                                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(Brush.linearGradient(listOf(Navy, Color(0xFF245477)))).padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Text("MACHINE SHOP OPERATIONS", color = Color(0xFFFFB74D), fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.1.sp)
                                    Text("Production Review", color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.Bold)
                                    Text("Secure access to production, quality and action workflows.", color = Color(0xFFD9E6F0), fontSize = 13.sp)
                                }
                                Text("SECURE SIGN IN",color=Muted,fontSize=12.sp,fontWeight=FontWeight.Bold,letterSpacing=1.2.sp)
                                Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(18.dp),colors=CardDefaults.cardColors(containerColor=Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border),elevation=CardDefaults.cardElevation(2.dp)) {
                                    Column(Modifier.padding(20.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
                                        Text("Sign in",color=Navy,fontSize=21.sp,fontWeight=FontWeight.Bold)
                                        Text("Use your existing Production Review account.",color=Muted,fontSize=14.sp)
                                        OutlinedTextField(username,{username=it},label={Text("Username")},singleLine=true,modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(password,{password=it},label={Text("Password")},singleLine=true,visualTransformation=PasswordVisualTransformation(),modifier=Modifier.fillMaxWidth())
                                        Button(onClick={
                                            if(username.isBlank()||password.isBlank()) message="Enter both username and password."
                                            else { busy=true; message="Signing in…"; scope.launch {
                                                try {
                                                    val result=withContext(Dispatchers.IO){ApiClient.login(username.trim(),password)}
                                                    withContext(Dispatchers.IO){sessionStore.save(result.first)}
                                                    token=result.first; account=result.second; password=""; refreshPendingActions(result.first)
                                                    refreshMasters(result.first); message="Signed in. Loading masters…"
                                                } catch(e:Exception){
                                                    message=e.message?.takeIf { it.isNotBlank() } ?: "Unable to sign in. Check your connection and try again."
                                                } finally{busy=false}
                                            }}
                                        },enabled=!busy,modifier=Modifier.fillMaxWidth().height(50.dp),colors=ButtonDefaults.buttonColors(containerColor=Teal)) { Text(if(busy)"PLEASE WAIT…" else "SIGN IN") }
                                        if (!busy && message != "Connect securely to your production account." && !message.startsWith("Signed in.")) {
                                            Card(
                                                modifier=Modifier.fillMaxWidth(),
                                                colors=CardDefaults.cardColors(containerColor=Color(0xFFFFF1F0)),
                                                border=androidx.compose.foundation.BorderStroke(1.dp, Color(0xFFF2C7C4)),
                                                shape=RoundedCornerShape(10.dp)
                                            ) {
                                                Text(message, modifier=Modifier.fillMaxWidth().padding(12.dp), color=Danger, fontSize=13.sp, fontWeight=FontWeight.Medium)
                                            }
                                        }
                                    }
                                }
                            } else {
                                val isManager = account!!.role.uppercase() in listOf("ADMIN", "MANAGEMENT")
                                val totalOpen = if (isManager) pendingActionGroups.sumOf { it.openCount } else pendingActions.size
                                val totalOverdue = if (isManager) pendingActionGroups.sumOf { it.overdueCount } else pendingActions.count { it.overdue }
                                val dueToday = if (isManager) pendingActionGroups.sumOf { it.dueTodayCount } else pendingActions.count { it.due.substringBefore("T") == LocalDate.now().toString() }
                                if (homeTab != "OEE") {
                                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        MetricTile("OPEN ACTIONS", totalOpen.toString(), Teal, Modifier.weight(1f))
                                        MetricTile("OVERDUE", totalOverdue.toString(), Danger, Modifier.weight(1f))
                                        MetricTile("DUE TODAY", dueToday.toString(), Warning, Modifier.weight(1f))
                                    }
                                }
                                if(homeTab=="ACTIONS") {
                                    if (account!!.role.uppercase() in listOf("ADMIN", "MANAGEMENT")) {
                                        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically) {
                                            Text("Pending actions by user",color=Navy,fontSize=19.sp,fontWeight=FontWeight.Bold)
                                            Text("${pendingActionGroups.sumOf { it.openCount }} open",color=Muted,fontSize=12.sp)
                                        }
                                        if (pendingActionGroups.isEmpty()) EmptyState("No open actions", "There are no open actions assigned across the team.", { Icon(Icons.Filled.Assignment, contentDescription = null, tint = Teal, modifier = Modifier.size(30.dp)) })
                                        pendingActionGroups.forEach { group ->
                                            Card(Modifier.fillMaxWidth().clickable { selectedOwner=group;homeTab="USER_ACTIONS" },shape=RoundedCornerShape(15.dp),colors=CardDefaults.cardColors(containerColor=Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border),elevation=CardDefaults.cardElevation(1.dp)) {
                                                Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(5.dp)) {
                                                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
                                                        Text(group.name,color=Navy,fontWeight=FontWeight.Bold)
                                                        Text("${group.openCount} OPEN",color=Teal,fontWeight=FontWeight.Bold,fontSize=11.sp)
                                                    }
                                                    Text(group.role.replace("_"," "),color=Muted,fontSize=11.sp)
                                                    Text("${group.overdueCount} overdue  •  ${group.dueTodayCount} due today",color=if(group.overdueCount>0) Color(0xFFB3261E) else Muted,fontSize=12.sp)
                                                    Text("VIEW USER ACTIONS →",color=Teal,fontSize=11.sp,fontWeight=FontWeight.Bold)
                                                }
                                            }
                                        }
                                    } else {
                                        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically) {
                                            Text("My pending actions",color=Navy,fontSize=19.sp,fontWeight=FontWeight.Bold)
                                            Text("${pendingActions.size} open",color=Muted,fontSize=12.sp)
                                        }
                                        if(pendingActions.isEmpty()) EmptyState("You're all caught up", "No pending actions are currently assigned to you.", { Icon(Icons.Filled.Assignment, contentDescription = null, tint = Teal, modifier = Modifier.size(30.dp)) })
                                    }
                                    pendingActions.forEach { item ->
                                        Card(Modifier.fillMaxWidth().clickable { token?.let{openAction(item,it)} },shape=RoundedCornerShape(15.dp),colors=CardDefaults.cardColors(containerColor=Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border),elevation=CardDefaults.cardElevation(1.dp)) {
                                            Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(5.dp)) {
                                                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
                                                    Text(item.number,color=Navy,fontWeight=FontWeight.Bold)
                                                    StatusPill(if(item.overdue) "OVERDUE" else item.status.replace("_"," "), if(item.overdue) Danger else Success)
                                                }
                                                Text(item.description,color=Navy)
                                                Text("${if(item.whyWhy) "WHY-WHY ESCALATION" else "ACTION REQUIRED"} • ${item.priority}",color=Muted,fontSize=11.sp)
                                                if(item.whyWhy) LinearProgressIndicator(progress={item.completion/100f},modifier=Modifier.fillMaxWidth())
                                                Text("Tap to update action →",color=Teal,fontSize=12.sp,fontWeight=FontWeight.SemiBold)
                                            }
                                        }
                                    }
                                } else if (homeTab=="USER_ACTIONS" && selectedOwner!=null) {
                                    val owner=selectedOwner!!
                                    TextButton(onClick={selectedOwner=null;homeTab="ACTIONS";token?.let{refreshPendingActions(it)}}){Text("← BACK TO USERS")}
                                    Text(owner.name,color=Navy,fontSize=20.sp,fontWeight=FontWeight.Bold)
                                    Text("${owner.openCount} open • ${owner.overdueCount} overdue • ${owner.dueTodayCount} due today",color=Muted,fontSize=12.sp)
                                    owner.actions.forEach { item ->
                                        Card(Modifier.fillMaxWidth().clickable { token?.let{openAction(item,it)} },colors=CardDefaults.cardColors(containerColor=Color.White)) {
                                            Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(5.dp)) {
                                                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
                                                    Text(item.number,color=Navy,fontWeight=FontWeight.Bold)
                                                    StatusPill(if(item.overdue) "OVERDUE" else item.status.replace("_"," "), if(item.overdue) Danger else Success)
                                                }
                                                Text(item.description,color=Navy)
                                                Text("${if(item.whyWhy) "WHY-WHY ESCALATION" else "ACTION REQUIRED"} • ${item.priority}",color=Muted,fontSize=11.sp)
                                                if(item.whyWhy) LinearProgressIndicator(progress={item.completion/100f},modifier=Modifier.fillMaxWidth())
                                                Text("Tap to update action →",color=Teal,fontSize=12.sp,fontWeight=FontWeight.SemiBold)
                                            }
                                        }
                                    }
                                } else if(homeTab=="DETAIL" && selectedAction!=null) {
                                    val item=selectedAction!!
                                    TextButton(onClick={homeTab=if(account?.role?.uppercase() in listOf("ADMIN","MANAGEMENT")) "USER_ACTIONS" else "ACTIONS";token?.let{refreshPendingActions(it)}}) { Text("← BACK TO ACTIONS") }
                                    OutlinedButton(onClick={val auth=token;if(auth==null)message="Please sign in again." else scope.launch {homeTab="HISTORY";actionHistoryLoading=true;actionHistoryError=null;try{actionHistory=withContext(Dispatchers.IO){ApiClient.loadActionHistory(item.id,auth)}}catch(e:Exception){actionHistoryError=e.message ?: "Unable to load action history."}finally{actionHistoryLoading=false}}},modifier=Modifier.fillMaxWidth()){Text("VIEW ACTION HISTORY")}
                                    Card(Modifier.fillMaxWidth(), shape=RoundedCornerShape(16.dp), colors=CardDefaults.cardColors(containerColor=Color.White), border=androidx.compose.foundation.BorderStroke(1.dp,Border)) {
                                        Column(Modifier.padding(16.dp), verticalArrangement=Arrangement.spacedBy(8.dp)) {
                                            Text(item.number,color=Navy,fontSize=20.sp,fontWeight=FontWeight.Bold)
                                            Text(item.description,color=Muted,fontSize=14.sp)
                                            StatusPill(if(item.overdue) "OVERDUE" else item.status.replace("_"," "), if(item.overdue) Danger else Success)
                                            Text(if(item.whyWhy) "WHY-WHY ESCALATION" else "ACTION REQUIRED",color=Teal,fontWeight=FontWeight.Bold,fontSize=11.sp)
                                        }
                                    }
                                    SectionLabel("Progress update", "Describe the work completed or action taken")
                                    OutlinedTextField(followupComment,{followupComment=it},label={Text("Action taken / progress update *")},modifier=Modifier.fillMaxWidth(),minLines=3,shape=RoundedCornerShape(12.dp))
                                    OutlinedButton(onClick={evidencePicker.launch("*/*")},enabled=!busy,modifier=Modifier.fillMaxWidth().heightIn(min=50.dp),shape=RoundedCornerShape(12.dp)) { Text(if(evidenceFile==null)"ADD EVIDENCE PHOTO / DOCUMENT" else "CHANGE EVIDENCE FILE") }
                                    evidenceFile?.let { Text("Selected: ${it.name} • ${(it.length()/1024).coerceAtLeast(1)} KB",color=Muted,fontSize=12.sp) }
                                    SectionLabel("Update status", "Choose the current action state")
                                    Row(horizontalArrangement=Arrangement.spacedBy(6.dp)) {
                                        listOf("OPEN","IN_PROGRESS","BLOCKED").forEach { st -> FilterChip(selected=actionStatus==st,onClick={actionStatus=st},label={Text(st.replace("_"," "))}) }
                                    }
                                    if(item.whyWhy) {
                                        SectionLabel("Why-Why investigation", "Record the cause and actions in sequence")
                                        OutlinedTextField(why1,{why1=it},label={Text("Why 1")},modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(why2,{why2=it},label={Text("Why 2")},modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(why3,{why3=it},label={Text("Why 3")},modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(why4,{why4=it},label={Text("Why 4")},modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(why5,{why5=it},label={Text("Why 5")},modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(rootCause,{rootCause=it},label={Text("Root cause")},modifier=Modifier.fillMaxWidth(),minLines=2)
                                        OutlinedTextField(correctiveAction,{correctiveAction=it},label={Text("Corrective action")},modifier=Modifier.fillMaxWidth(),minLines=2)
                                        OutlinedTextField(preventiveAction,{preventiveAction=it},label={Text("Preventive action")},modifier=Modifier.fillMaxWidth(),minLines=2)
                                        OutlinedTextField(verificationMethod,{verificationMethod=it},label={Text("Verification method")},modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(verificationResult,{verificationResult=it},label={Text("Verification result")},modifier=Modifier.fillMaxWidth())
                                        Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                                             Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                                 Text("WHY-WHY COMPLETION", color = Muted, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                                                 Text("${item.completion}%", color = Teal, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                                             }
                                             LinearProgressIndicator(progress = { (item.completion / 100f).coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth().height(7.dp), color = Teal, trackColor = Border)
                                         }
                                    }
                                    Button(onClick={
                                        val auth=token
                                        if(auth==null) message="Please sign in again."
                                        else if(followupComment.isBlank()) message="Enter action taken / progress before submitting."
                                        else scope.launch {
                                            busy=true
                                            if(!submissionStarted) { pendingFollowupComment=followupComment.trim();pendingActionStatus=actionStatus;submissionStarted=true }
                                            try {
                                                if(item.whyWhy && !whyWhySavedPending) {
                                                    val plan=JSONObject().put("why1",why1).put("why2",why2).put("why3",why3).put("why4",why4).put("why5",why5).put("root_cause",rootCause).put("corrective_action",correctiveAction).put("preventive_action",preventiveAction).put("verification_method",verificationMethod).put("verification_result",verificationResult)
                                                    withContext(Dispatchers.IO){ApiClient.updateWhyWhy(item.id,plan,auth)}
                                                    whyWhySavedPending=true
                                                }
                                                if(evidenceFile!=null && !evidenceUploadedPending) {
                                                    val evidence=evidenceFile!!
                                                    withContext(Dispatchers.IO){ApiClient.uploadActionEvidence(item.id,evidence,auth)}
                                                    evidence.delete();evidenceFile=null;evidenceUploadedPending=true
                                                }
                                                if(!actionUpdateSavedPending) {
                                                    withContext(Dispatchers.IO){ApiClient.updateAction(item.id,pendingFollowupComment,pendingActionStatus,auth)}
                                                    actionUpdateSavedPending=true
                                                }
                                                whyWhySavedPending=false;evidenceUploadedPending=false;actionUpdateSavedPending=false
                                                pendingFollowupComment="";pendingActionStatus=actionStatus;submissionStarted=false
                                                followupComment=""
                                                message="Action update submitted successfully."
                                                refreshPendingActions(auth)
                                                homeTab="HISTORY";actionHistoryLoading=true;actionHistoryError=null
                                                try { actionHistory=withContext(Dispatchers.IO){ApiClient.loadActionHistory(item.id,auth)} }
                                                catch(historyError:Exception){actionHistoryError=historyError.message ?: "Unable to refresh action history."}
                                                finally{actionHistoryLoading=false}
                                                try {
                                                    val refreshed=withContext(Dispatchers.IO){ApiClient.loadActionPlan(item.id,auth)}
                                                    val rows=refreshed.optJSONArray("attachments") ?: JSONArray()
                                                    actionAttachments=(0 until rows.length()).map{rows.getJSONObject(it)}
                                                } catch(refreshError:Exception) { message="Action update saved. Evidence list refresh failed: "+(refreshError.message ?: "Please reopen the action.") }
                                            } catch(e:Exception){message=e.message ?: "Unable to submit action update. Retry; completed steps will not be repeated."}
                                            finally{busy=false}
                                        }
                                    },enabled=!busy,modifier=Modifier.fillMaxWidth()) { Text(if(busy)"SAVING…" else "SUBMIT ACTION UPDATE") }
                                }
                                if(homeTab=="OEE") {
                                    ScreenTitle("Machine effectiveness", "Production entry, shift performance and loss analysis")
                                    Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(16.dp),colors=CardDefaults.cardColors(containerColor=Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border)) {
                                        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
                                            Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                                                Icon(Icons.Filled.Settings,contentDescription=null,tint=Teal,modifier=Modifier.size(19.dp))
                                                Text("PRODUCTION SCOPE",color=Navy,fontSize=12.sp,fontWeight=FontWeight.ExtraBold,letterSpacing=0.8.sp)
                                            }
                                            ChoiceDropdown("Product / Part number",masters?.products.orEmpty(),oeeProduct,{selected ->
                                                oeeProduct=selected
                                                oeeOperation=null
                                                oeeMachine=null
                                                oeeRoutes=emptyList()
                                                oeeMachines=emptyList()
                                                oeeSummary=null
                                                oeeError=null
                                                oeeMode="ENTRY"
                                                oeeEntryId=null
                                                oeeEntryLosses=listOf(OeeLossDraft())
                                                val auth=token
                                                if(auth!=null) loadOeeScope(auth,selected)
                                                else oeeError="Please sign in again."
                                            })
                                            OutlinedTextField(value=oeeDate,onValueChange={},readOnly=true,label={Text("Production date")},singleLine=true,trailingIcon={IconButton(onClick={showOeeDatePicker=true}){Icon(Icons.Filled.DateRange,contentDescription="Choose production date")}},modifier=Modifier.fillMaxWidth().clickable{showOeeDatePicker=true})
                                            if(showOeeDatePicker) {
                                                val pickerState=rememberDatePickerState(initialSelectedDateMillis=runCatching{LocalDate.parse(oeeDate).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()}.getOrDefault(System.currentTimeMillis()))
                                                DatePickerDialog(onDismissRequest={showOeeDatePicker=false},confirmButton={TextButton(onClick={
                                                    pickerState.selectedDateMillis?.let{millis->
                                                        val selectedDate=Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate().toString()
                                                        if(selectedDate!=oeeDate){
                                                            oeeDate=selectedDate
                                                            oeeSummary=null
                                                            oeeRoutes=emptyList()
                                                            oeeMachines=emptyList()
                                                            oeeOperation=null
                                                            oeeMachine=null
                                                            val auth=token
                                                            val product=oeeProduct
                                                            if(auth!=null && product!=null) loadOeeScope(auth,product)
                                                        }
                                                    }
                                                    showOeeDatePicker=false
                                                }){Text("OK")}},dismissButton={TextButton(onClick={showOeeDatePicker=false}){Text("CANCEL")}}){DatePicker(state=pickerState)}
                                            }
                                            Column(verticalArrangement=Arrangement.spacedBy(5.dp)) {
                                                Text("Shift",color=Muted,fontSize=12.sp,fontWeight=FontWeight.Medium)
                                                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                                                    listOf("A","B","C").forEach { shiftOption ->
                                                        FilterChip(
                                                            selected=oeeShift==shiftOption,
                                                            onClick={
                                                                if(oeeShift!=shiftOption) {
                                                                    oeeShift=shiftOption
                                                                    oeeSummary=null
                                                                    oeeError=null
                                                                }
                                                            },
                                                            label={Text("Shift $shiftOption",maxLines=1,fontSize=12.sp)},
                                                            modifier=Modifier.weight(1f)
                                                        )
                                                    }
                                                }
                                            }
                                            if(oeeLoading) {
                                                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.Center,verticalAlignment=Alignment.CenterVertically) {
                                                    CircularProgressIndicator(modifier=Modifier.size(18.dp),strokeWidth=2.dp)
                                                    Spacer(Modifier.width(8.dp))
                                                    Text("Loading applicable operations and machines…",color=Muted,fontSize=12.sp)
                                                }
                                            }
                                            if(oeeRoutes.isNotEmpty()) ChoiceDropdown("Operation",oeeRoutes.map{Choice(it.id,it.label)},oeeOperation?.let{Choice(it.id,it.label)},{selected->
                                                oeeOperation=oeeRoutes.firstOrNull{it.id==selected.id};oeeMachine=null;oeeMachines=emptyList();oeeSummary=null
                                                val auth=token
                                                if(auth!=null) scope.launch {
                                                    oeeLoading=true
                                                    try { val loaded=withContext(Dispatchers.IO){ApiClient.loadOeeMachines(selected.id,oeeDate,auth)};oeeMachines=loaded;oeeMachine=loaded.firstOrNull() }
                                                    catch(e:Exception){oeeError=userFriendlyOeeError(e,"Could not load machines for this operation. Check your connection and try again.")}
                                                    finally{oeeLoading=false}
                                                }
                                            })
                                            if(oeeMachines.isNotEmpty()) ChoiceDropdown("Machine",oeeMachines,oeeMachine,{oeeMachine=it;oeeSummary=null})

                                            Button(onClick={token?.let{refreshOee(it)} ?: run{oeeError="Please sign in again."}},enabled=!oeeLoading&&oeeMachine!=null,modifier=Modifier.fillMaxWidth()) { Text("REFRESH OEE") }
                                            
                                        }
                                    }
                                    Surface(Modifier.fillMaxWidth(),shape=RoundedCornerShape(14.dp),color=Color(0xFFE8EEF3),border=androidx.compose.foundation.BorderStroke(1.dp,Border)) {
                                        Row(Modifier.fillMaxWidth().padding(5.dp),horizontalArrangement=Arrangement.spacedBy(5.dp)) {
                                            listOf("ENTRY","SUMMARY","MANAGEMENT").forEach { mode ->
                                                val active=oeeMode==mode
                                                Surface(Modifier.weight(1f).clip(RoundedCornerShape(10.dp)).clickable { oeeMode=mode },shape=RoundedCornerShape(10.dp),color=if(active)Color.White else Color.Transparent,shadowElevation=if(active)2.dp else 0.dp) {
                                                    Text(if(mode=="ENTRY")"NEW ENTRY" else mode,modifier=Modifier.padding(vertical=11.dp,horizontal=3.dp),color=if(active)Teal else Muted,fontSize=10.sp,fontWeight=FontWeight.ExtraBold,textAlign=androidx.compose.ui.text.style.TextAlign.Center,maxLines=1)
                                                }
                                            }
                                        }
                                    }
                                        oeeSavedSummary?.let { summary ->
                                            AlertDialog(
                                                onDismissRequest = { oeeSavedSummary = null },
                                                title = { Text("Production saved", color = Navy, fontWeight = FontWeight.Bold) },
                                                text = {
                                                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                                        Text("OEE PERFORMANCE SUMMARY", color = Teal, fontSize = 11.sp, fontWeight = FontWeight.ExtraBold)
                                                        summary.lines().forEachIndexed { index, line ->
                                                            Text(line, color = if(index == 1) Teal else Muted, fontSize = if(index == 1) 17.sp else 13.sp, fontWeight = if(index == 1) FontWeight.Bold else FontWeight.Medium)
                                                        }
                                                    }
                                                },
                                                confirmButton = { TextButton(onClick = { oeeSavedSummary = null }) { Text("OK", color = Teal, fontWeight = FontWeight.Bold) } },
                                                containerColor = Color.White,
                                                shape = RoundedCornerShape(16.dp)
                                            )
                                        }
                                        oeeSuccess?.let { success ->
                                            Card(
                                                colors = CardDefaults.cardColors(containerColor = Color(0xFFEAF6F2)),
                                                shape = RoundedCornerShape(12.dp),
                                                border = androidx.compose.foundation.BorderStroke(1.dp, Color(0xFFCBE8DD))
                                            ) {
                                                Text(success, modifier = Modifier.fillMaxWidth().padding(12.dp),
                                                    color = Success, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                                            }
                                        }
                                    if(oeeMode=="SUMMARY") {
                                        SectionLabel("Selected scope OEE", "Live figures for the selected part, process, machine, date and shift")
                                        val selectedSummary = oeeSummary?.optJSONObject("summary")
                                        val selectedEntries = oeeSummary?.optJSONArray("entries") ?: JSONArray()
                                        val selectedLosses = oeeSummary?.optJSONArray("losses") ?: JSONArray()
                                        Card(
                                            Modifier.fillMaxWidth(),
                                            shape=RoundedCornerShape(14.dp),
                                            colors=CardDefaults.cardColors(containerColor=Color.White),
                                            border=androidx.compose.foundation.BorderStroke(1.dp,Border)
                                        ) {
                                            Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
                                                Text(
                                                    listOfNotNull(oeeProduct?.label, oeeOperation?.label, oeeMachine?.label).joinToString("  ›  ").ifBlank { "No scope selected" },
                                                    color=Navy,fontSize=12.sp,fontWeight=FontWeight.SemiBold
                                                )
                                                Text("$oeeDate • Shift $oeeShift",color=Muted,fontSize=11.sp)
                                                if (selectedSummary == null) {
                                                    EmptyState(
                                                        if (oeeLoading) "Loading OEE summary" else "No OEE records for this scope",
                                                        if (oeeProduct == null || oeeOperation == null || oeeMachine == null)
                                                            "Select a part to load its applicable operations and available machines automatically."
                                                        else "No saved production entry was found for this date and shift. Use Production Entry to record output."
                                                    )
                                                } else {
                                                    Text("${"%.1f".format(selectedSummary.optDouble("oee_reported")*100)}%",color=Navy,fontSize=32.sp,fontWeight=FontWeight.ExtraBold)
                                                    Text("REPORTED OEE",color=Muted,fontSize=10.sp,fontWeight=FontWeight.Bold)
                                                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(6.dp)) {
                                                        MetricTile("Availability","${"%.1f".format(selectedSummary.optDouble("availability")*100)}%",Teal,Modifier.weight(1f),compact=true)
                                                        MetricTile("Performance","${"%.1f".format(selectedSummary.optDouble("performance_capped")*100)}%",Warning,Modifier.weight(1f),compact=true)
                                                        MetricTile("Quality","${"%.1f".format(selectedSummary.optDouble("quality")*100)}%",Success,Modifier.weight(1f),compact=true)
                                                    }
                                                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(6.dp)) {
                                                        MetricTile("Planned time","${"%.0f".format(selectedSummary.optDouble("planned_production_min"))} min",Navy,Modifier.weight(1f),compact=true)
                                                        MetricTile("Run time","${"%.0f".format(selectedSummary.optDouble("run_time_min"))} min",Teal,Modifier.weight(1f),compact=true)
                                                    }
                                                    val selectedGoodQty = (0 until selectedEntries.length()).sumOf { selectedEntries.getJSONObject(it).optDouble("good_count",0.0) }
                                                    Text("Output: ${selectedGoodQty.toLong()} good • ${selectedSummary.optDouble("reject_or_unaccounted_count",0.0).toLong()} rejected / unclassified",color=Muted,fontSize=11.sp)
                                                    Text("Availability loss: ${"%.1f".format(selectedSummary.optDouble("captured_loss_min"))} min • Unclassified downtime: ${"%.1f".format(selectedSummary.optDouble("unclassified_loss_min"))} min",color=Muted,fontSize=11.sp)
                                                }
                                                OutlinedButton(
                                                    onClick={token?.let{refreshOee(it)} ?: run{oeeError="Please sign in again."}},
                                                    enabled=!oeeLoading && oeeMachine!=null,
                                                    modifier=Modifier.fillMaxWidth()
                                                ) { Text(if(oeeLoading) "REFRESHING…" else "REFRESH SELECTED SCOPE") }
                                            }
                                        }
                                        SectionLabel("Production records", "${selectedEntries.length()} record(s) for this selected scope")
                                        if(selectedEntries.length()==0) {
                                            EmptyState("No production entries", "Load Production Entry to record the selected machine shift.")
                                        } else {
                                            for(i in 0 until selectedEntries.length()) {
                                                val entry=selectedEntries.getJSONObject(i)
                                                Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(12.dp),colors=CardDefaults.cardColors(containerColor=Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border)) {
                                                    Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(5.dp)) {
                                                        Text("Entry #${entry.optInt("id")} • ${entry.optString("production_date")} • Shift ${entry.optString("shift")}",color=Navy,fontWeight=FontWeight.Bold,fontSize=13.sp)
                                                        Text("Operator: ${entry.optString("operator_name").takeIf{it.isNotBlank() && it!="null"} ?: "Not recorded"}",color=Teal,fontSize=11.sp,fontWeight=FontWeight.SemiBold)
                                                        Text("Total ${entry.optDouble("total_count").toLong()} • Good ${entry.optDouble("good_count").toLong()} • Reject ${entry.optDouble("reject_count").toLong()}",color=Muted,fontSize=12.sp)
                                                        Text("OEE ${"%.1f".format(entry.optDouble("oee_reported")*100)}%  |  A ${"%.1f".format(entry.optDouble("availability")*100)}%  P ${"%.1f".format(entry.optDouble("performance_capped")*100)}%  Q ${"%.1f".format(entry.optDouble("quality")*100)}%",color=Teal,fontSize=12.sp,fontWeight=FontWeight.SemiBold)
                                                        OutlinedButton(onClick={editOeeEntry(entry.optString("production_date"), entry.optString("shift"), entry.optInt("id"))}, modifier=Modifier.fillMaxWidth(), enabled=!oeeLoading) { Text("EDIT THIS RECORD") }
                                                    }
                                                }
                                            }
                                        }

                                        Spacer(Modifier.height(8.dp))
                                        SectionLabel("Last 7 days • Shift $oeeShift", "${oeeRecentRecords.size} record(s) from ${runCatching { LocalDate.parse(oeeDate).minusDays(6) }.getOrNull() ?: oeeDate} to $oeeDate")
                                        when {
                                            oeeRecentLoading -> Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.Center,verticalAlignment=Alignment.CenterVertically) {
                                                CircularProgressIndicator(modifier=Modifier.size(18.dp),strokeWidth=2.dp)
                                                Spacer(Modifier.width(8.dp))
                                                Text("Loading last 7 days…",color=Muted,fontSize=12.sp)
                                            }
                                            oeeRecentError != null -> Text(oeeRecentError!!,color=Danger,fontSize=12.sp)
                                            oeeRecentRecords.isEmpty() -> EmptyState("No OEE records in the last 7 days", "No saved entries were found for Shift $oeeShift in the selected part, operation and machine.")
                                            else -> oeeRecentRecords.forEach { entry ->
                                                Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(12.dp),colors=CardDefaults.cardColors(containerColor=Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border)) {
                                                    Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(5.dp)) {
                                                        Text("${entry.optString("production_date")} • Shift ${entry.optString("shift")}",color=Navy,fontWeight=FontWeight.Bold,fontSize=13.sp)
                                                        Text("Total ${entry.optDouble("total_count").toLong()} • Good ${entry.optDouble("good_count").toLong()} • Reject ${entry.optDouble("reject_count").toLong()}",color=Muted,fontSize=12.sp)
                                                        Text("OEE ${"%.1f".format(entry.optDouble("oee_reported")*100)}%  |  A ${"%.1f".format(entry.optDouble("availability")*100)}%  P ${"%.1f".format(entry.optDouble("performance_capped")*100)}%  Q ${"%.1f".format(entry.optDouble("quality")*100)}%",color=Teal,fontSize=12.sp,fontWeight=FontWeight.SemiBold)
                                                        OutlinedButton(onClick={editOeeEntry(entry.optString("production_date"), entry.optString("shift"), entry.optInt("id"))}, modifier=Modifier.fillMaxWidth(), enabled=!oeeLoading) { Text("EDIT THIS RECORD") }
                                                    }
                                                }
                                            }
                                        }
                                        SectionLabel("Loss events", "${selectedLosses.length()} classified event(s)")
                                        if(selectedLosses.length()==0) Text("No loss events recorded for this scope.",color=Muted,fontSize=12.sp)
                                        else for(i in 0 until selectedLosses.length()) {
                                            val loss=selectedLosses.getJSONObject(i)
                                            Text("${loss.optString("category")} • ${loss.optString("component")} • ${"%.1f".format(loss.optDouble("duration_min"))} min",color=Navy,fontSize=12.sp)
                                        }
                                    } else if(oeeMode=="ENTRY") {
                                        SectionLabel(if(oeeEntryId!=null) "Correct production record" else "New production entry", "Enter operator, shift time and production quantities. Calculations update from your inputs.")
                                        if(oeeEntryId==null && !oeeLoading) {
                                            val readyPulse = rememberInfiniteTransition(label="newEntryReadyPulse")
                                            val readyAlpha by readyPulse.animateFloat(
                                                initialValue=0.55f,
                                                targetValue=1.0f,
                                                animationSpec=infiniteRepeatable(
                                                    animation=tween(durationMillis=850,easing=FastOutSlowInEasing),
                                                    repeatMode=RepeatMode.Reverse
                                                ),
                                                label="newEntryReadyAlpha"
                                            )
                                            Row(
                                                Modifier.fillMaxWidth()
                                                    .clip(RoundedCornerShape(10.dp))
                                                    .background(Color(0xFFEAF5F5))
                                                    .border(1.dp,Color(0x8848E0B4),RoundedCornerShape(10.dp))
                                                    .padding(11.dp),
                                                verticalAlignment=Alignment.CenterVertically,
                                                horizontalArrangement=Arrangement.spacedBy(8.dp)
                                            ) {
                                                Box(Modifier.size(9.dp).clip(CircleShape).background(Color(0xFFFF3B30).copy(alpha=readyAlpha)))
                                                Text("NEW ENTRY  •  READY TO CAPTURE",color=Color(0xFF087F70).copy(alpha=readyAlpha),fontSize=11.sp,fontWeight=FontWeight.ExtraBold)
                                            }
                                        } else {
                                            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(if(oeeEntryId!=null)Color(0xFFFFF4E5) else Color(0xFFEAF5F5)).padding(11.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                                                Icon(if(oeeEntryId!=null)Icons.Filled.History else Icons.Filled.Assignment,contentDescription=null,tint=if(oeeEntryId!=null)Warning else Teal,modifier=Modifier.size(18.dp))
                                                Text(if(oeeLoading) "Loading production record…" else "CORRECTION MODE  •  RECORD #$oeeEntryId",color=Warning,fontSize=11.sp,fontWeight=FontWeight.ExtraBold)
                                            }
                                        }
                                        if(oeeEntryId!=null) {
                                            Text("Editing saved entry #${oeeEntryId}",color=Warning,fontWeight=FontWeight.Bold,fontSize=12.sp)
                                            OutlinedTextField(oeeCorrectionReason,{oeeCorrectionReason=it},label={Text("Correction reason (minimum 5 characters)")},modifier=Modifier.fillMaxWidth(),minLines=2)
                                        }
                                        Column(verticalArrangement=Arrangement.spacedBy(4.dp)) {
                                            OutlinedTextField(
                                                value=oeeOperatorName,
                                                onValueChange={value->
                                                    oeeOperatorName=value
                                                    oeeOperatorError=null
                                                    oeeOperatorId=oeeOperators.firstOrNull{it.label.equals(value.trim().replace(Regex("\\s+")," "),ignoreCase=true)}?.id
                                                    oeeOperatorMenu=true
                                                },
                                                label={Text("Operator name (first name and surname)")},
                                                placeholder={Text("Type name or use keyboard microphone")},
                                                modifier=Modifier.fillMaxWidth(),
                                                singleLine=true
                                            )
                                            val matchingOperators = if (oeeOperatorName.isBlank()) emptyList()
                                                else oeeOperators.filter { it.label.contains(oeeOperatorName.trim(), ignoreCase=true) }.take(8)
                                            if (oeeOperatorMenu && matchingOperators.isNotEmpty()) {
                                                Card(
                                                    modifier=Modifier.fillMaxWidth(),
                                                    colors=CardDefaults.cardColors(containerColor=Color.White),
                                                    border=androidx.compose.foundation.BorderStroke(1.dp, Border),
                                                    shape=RoundedCornerShape(10.dp)
                                                ) {
                                                    Column(Modifier.fillMaxWidth().padding(vertical=4.dp)) {
                                                        matchingOperators.forEach { option ->
                                                            TextButton(
                                                                onClick={
                                                                    oeeOperatorId=option.id
                                                                    oeeOperatorError=null
                                                                    oeeOperatorName=option.label
                                                                    oeeOperatorMenu=false
                                                                },
                                                                modifier=Modifier.fillMaxWidth()
                                                            ) {
                                                                Text(option.label, modifier=Modifier.fillMaxWidth(), color=Navy)
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                            if(oeeOperatorId==null && oeeOperatorName.trim().split(Regex("\\s+")).filter{it.isNotBlank()}.size>=2) {
                                                TextButton(
                                                    enabled=!oeeOperatorCreating && token!=null,
                                                    onClick={
                                                        val auth=token
                                                        if(auth==null) {
                                                            oeeOperatorError="Your session is not available. Please sign in again."
                                                        } else scope.launch {
                                                            oeeOperatorCreating=true
                                                            oeeOperatorError=null
                                                            oeeError=null
                                                            try {
                                                                val requestedName=oeeOperatorName.trim().replace(Regex("\\s+")," ")
                                                                val (created, duplicateWarning)=withContext(Dispatchers.IO){ApiClient.createOeeOperator(requestedName,auth)}
                                                                val refreshed=withContext(Dispatchers.IO){ApiClient.loadOeeOperators(auth)}
                                                                val registered=refreshed.firstOrNull{it.id==created.id}
                                                                    ?: refreshed.firstOrNull{it.label.equals(created.label,ignoreCase=true)}
                                                                    ?: created
                                                                oeeOperators=refreshed.ifEmpty { (oeeOperators.filterNot{it.id==registered.id}+registered).sortedBy{it.label} }
                                                                oeeOperatorId=registered.id
                                                                oeeOperatorName=registered.label
                                                                oeeOperatorMenu=false
                                                                oeeOperatorError=null
                                                                oeeSuccess=if(duplicateWarning) "Operator added. A matching name already exists; verify the person's identity." else "Operator registered successfully."
                                                            } catch(e:Exception) {
                                                                oeeOperatorError=e.message?.takeIf{it.isNotBlank()} ?: "Unable to add operator. Check connection and permissions, then retry."
                                                            } finally {
                                                                oeeOperatorCreating=false
                                                            }
                                                        }
                                                    }
                                                ) { Text(if(oeeOperatorCreating) "ADDING OPERATOR…" else "＋ Add new operator") }
                                            }
                                            oeeOperatorError?.let { Text(it,color=Danger,fontSize=12.sp) }
                                            Text("Use the microphone on your Android keyboard for voice typing. Review the name, then select or add it.",color=Muted,fontSize=10.sp)
                                        }
                                        OutlinedTextField(oeeShiftMinutes,{oeeShiftMinutes=it},label={Text("SHIFT DURATION (MIN)",color=Navy,fontWeight=FontWeight.Bold,fontSize=14.sp)},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(oeeBreakMinutes,{oeeBreakMinutes=it},label={Text("PLANNED BREAKS (MIN)",color=Navy,fontWeight=FontWeight.Bold,fontSize=14.sp)},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(oeeGoodCount,{oeeGoodCount=it},label={Text("GOOD QUANTITY",color=Navy,fontWeight=FontWeight.Bold,fontSize=14.sp)},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(oeeRejectCount,{oeeRejectCount=it},label={Text("REJECTED QUANTITY",color=Navy,fontWeight=FontWeight.Bold,fontSize=14.sp)},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
                                        Text("Total production: ${"%.3f".format((oeeGoodCount.toDoubleOrNull()?:0.0)+(oeeRejectCount.toDoubleOrNull()?:0.0)).trimEnd('0').trimEnd('.')} pcs",color=Success,fontWeight=FontWeight.Bold)
                                        OutlinedTextField(oeeEntryRemarks,{oeeEntryRemarks=it},label={Text("PRODUCTION REMARKS (OPTIONAL)",color=Navy,fontWeight=FontWeight.Bold,fontSize=14.sp)},modifier=Modifier.fillMaxWidth(),minLines=2)
                                        SectionLabel("Machine losses", "Choose a reason and enter minutes. A new card appears after completing a loss.")
                                        oeeEntryLosses.forEachIndexed { index, loss ->
                                            OutlinedButton(
                                                onClick = { editingLossIndex = index },
                                                modifier = Modifier.fillMaxWidth(),
                                                shape = RoundedCornerShape(10.dp),
                                                border = androidx.compose.foundation.BorderStroke(1.dp,Border),
                                                colors = ButtonDefaults.outlinedButtonColors(contentColor=Navy)
                                            ) {
                                                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically) {
                                                    Column(horizontalAlignment=Alignment.Start) {
                                                        Text(if(loss.saved) "Recorded Loss Event #${loss.id}" else "Loss Event ${index+1}",fontWeight=FontWeight.Bold)
                                                        Text(
                                                            "${loss.category.ifBlank { "Select loss reason" }} • ${loss.duration.ifBlank { "0" }} min",
                                                            color=Muted,fontSize=11.sp
                                                        )
                                                    }
                                                    Text(if(loss.saved) "EDIT" else "ADD / EDIT",color=Teal,fontWeight=FontWeight.Bold,fontSize=11.sp)
                                                }
                                            }
                                            if (editingLossIndex == index) {
                                                Dialog(onDismissRequest = { editingLossIndex = null }) {
                                                    Card(
                                                        modifier=Modifier.fillMaxWidth(),
                                                        shape=RoundedCornerShape(8.dp),
                                                        colors=CardDefaults.cardColors(containerColor=Color(0xFFF8FAFC)),
                                                        border=androidx.compose.foundation.BorderStroke(1.dp,Color(0xFFCBD5E1)),
                                                        elevation=CardDefaults.cardElevation(defaultElevation=12.dp)
                                                    ) {
                                                        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
                                                            Row(
                                                                Modifier.fillMaxWidth().background(Color(0xFFE8EEF5),RoundedCornerShape(5.dp)).padding(horizontal=12.dp,vertical=10.dp),
                                                                horizontalArrangement=Arrangement.SpaceBetween,
                                                                verticalAlignment=Alignment.CenterVertically
                                                            ) {
                                                                Text(if(loss.saved) "EDIT MACHINE LOSS" else "ADD MACHINE LOSS",color=Navy,fontWeight=FontWeight.ExtraBold,fontSize=14.sp)
                                                                TextButton(onClick={editingLossIndex=null}) { Text("✕",color=Navy) }
                                                            }
                                                            if(loss.saved) Text("Editing recorded loss event #${loss.id}",color=Warning,fontSize=12.sp,fontWeight=FontWeight.SemiBold)
                                                            ChoiceDropdown(
                                                                if(loss.saved) "Loss type" else "Loss reason",
                                                                oeeLossCategories.map{Choice(it.id,"${it.label} • ${it.extra}")},
                                                                oeeLossCategories.firstOrNull{it.id==loss.categoryId},
                                                                {selected->
                                                                    oeeEntryLosses=oeeEntryLosses.toMutableList().also{rows->rows[index]=loss.copy(categoryId=selected.id,category=selected.label,component=selected.extra);if(!loss.saved&&index==rows.lastIndex&&(loss.duration.toDoubleOrNull()?:0.0)>0)rows.add(OeeLossDraft())}
                                                                }
                                                            )
                                                            OutlinedTextField(loss.duration,{value->
                                                                val rows=oeeEntryLosses.toMutableList();rows[index]=loss.copy(duration=value);if(!loss.saved&&value.toDoubleOrNull()?.let{it>0}==true&&rows.lastOrNull()?.let{it.categoryId!=null&&it.duration.toDoubleOrNull()?.let{n->n>0}==true}==true)rows.add(OeeLossDraft());oeeEntryLosses=rows
                                                            },label={Text("LOSS TIME (MINUTES)",color=Navy,fontWeight=FontWeight.Bold,fontSize=14.sp)},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
                                                            if(isAvailabilityOeeLoss(loss, oeeLossCategories)) {
                                                                Card(
                                                                    modifier=Modifier.fillMaxWidth(),
                                                                    shape=RoundedCornerShape(8.dp),
                                                                    colors=CardDefaults.cardColors(containerColor=Color(0xFFEAF5F5)),
                                                                    border=androidx.compose.foundation.BorderStroke(1.dp,Color(0xFFB9DDE0))
                                                                ) {
                                                                    Row(Modifier.fillMaxWidth().padding(12.dp),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically) {
                                                                        Column {
                                                                            Text("QUANTITY LOSS",color=Muted,fontSize=10.sp,fontWeight=FontWeight.Bold)
                                                                            Text(if(oeeIdealCycleSeconds==null) "Standard cycle time unavailable" else "Auto-calculated",color=Muted,fontSize=10.sp)
                                                                        }
                                                                        Text(if(oeeIdealCycleSeconds==null) "— pcs" else "${"%.0f".format(resolvedOeeLossQuantity(loss,oeeIdealCycleSeconds,oeeLossCategories))} pcs",color=Navy,fontSize=18.sp,fontWeight=FontWeight.ExtraBold)
                                                                    }
                                                                }
                                                            } else {
                                                                OutlinedTextField(loss.qty,{value->oeeEntryLosses=oeeEntryLosses.toMutableList().also{it[index]=loss.copy(qty=value)}},label={Text("QUANTITY LOSS (PCS)",color=Navy,fontWeight=FontWeight.Bold,fontSize=14.sp)},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
                                                            }
                                                            OutlinedTextField(loss.remark,{value->oeeEntryLosses=oeeEntryLosses.toMutableList().also{it[index]=loss.copy(remark=value)}},label={Text("REASON / DETAILS",color=Navy,fontWeight=FontWeight.Bold,fontSize=14.sp)},modifier=Modifier.fillMaxWidth(),minLines=2)
                                                            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.End,verticalAlignment=Alignment.CenterVertically) {
                                                                if(!loss.saved && oeeEntryLosses.size>1) TextButton(onClick={oeeEntryLosses=oeeEntryLosses.filterIndexed{idx,_->idx!=index};editingLossIndex=null}) { Text("REMOVE",color=Danger) }
                                                                TextButton(onClick={editingLossIndex=null}) { Text("CANCEL",color=Muted) }
                                                                Button(onClick={editingLossIndex=null},colors=ButtonDefaults.buttonColors(containerColor=Teal)) { Text("SAVE LOSS") }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        val availabilityLossTotal=oeeEntryLosses.filter{it.categoryId!=null && (isAvailabilityOeeLoss(it,oeeLossCategories))}.sumOf{it.duration.toDoubleOrNull()?:0.0}
                                        Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(12.dp),colors=CardDefaults.cardColors(containerColor=Color(0xFFFFF5E8)),border=androidx.compose.foundation.BorderStroke(1.dp,Color(0xFFF2D8B5))) {
                                            Row(Modifier.fillMaxWidth().padding(13.dp),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically) {
                                                Column(verticalArrangement=Arrangement.spacedBy(2.dp)) {
                                                    Text("AVAILABILITY DOWNTIME",color=Muted,fontSize=10.sp,fontWeight=FontWeight.Bold)
                                                    Text("Classified machine losses",color=Muted,fontSize=10.sp)
                                                }
                                                Text("${"%.1f".format(availabilityLossTotal)} min",color=Warning,fontSize=18.sp,fontWeight=FontWeight.ExtraBold)
                                            }
                                        }
                                        Button(onClick={
                                            val auth=token;val p=oeeProduct;val op=oeeOperation;val m=oeeMachine
                                            if(auth==null||p==null||op==null||m==null)oeeError="Select product, operation and machine first."
                                            else if(oeeOperatorId==null)oeeError="Select or add an operator name before saving."
                                            else if((oeeGoodCount.toDoubleOrNull()?:-1.0)<0||(oeeRejectCount.toDoubleOrNull()?:-1.0)<0)oeeError="Enter valid non-negative production quantities."
                                            else if(oeeEntryId!=null&&oeeCorrectionReason.trim().length<5)oeeError="Enter a correction reason of at least 5 characters."
                                            else scope.launch {
                                                oeeLoading=true;oeeError=null
                                                try {
                                                    // Correct existing loss events individually before recalculating entry downtime.
                                                    // The backend correction endpoint appends new losses; saved losses must never be re-posted.
                                                    val savedLossEdits=oeeEntryLosses.filter{it.saved&&it.id!=null}
                                                    savedLossEdits.forEach{loss->
                                                        val lossPayload=JSONObject()
                                                            .put("loss_date",oeeDate).put("shift",oeeShift)
                                                            .put("product_id",p.id).put("route_operation_id",op.id).put("machine_id",m.id)
                                                            .put("loss_category_id",loss.categoryId)
                                                            .put("duration_min",loss.duration.toDouble())
                                                            .put("qty_loss",resolvedOeeLossQuantity(loss,oeeIdealCycleSeconds,oeeLossCategories))
                                                            .put("remark",loss.remark)
                                                        if(loss.startTime.isNotBlank())lossPayload.put("start_time",loss.startTime)
                                                        if(loss.endTime.isNotBlank())lossPayload.put("end_time",loss.endTime)
                                                        withContext(Dispatchers.IO){ApiClient.correctOeeLoss(loss.id!!,lossPayload,oeeCorrectionReason.trim(),auth)}
                                                    }
                                                    val lossRows=oeeEntryLosses.filter{!it.saved&&it.categoryId!=null&&(it.duration.toDoubleOrNull()?:0.0)>0}
                                                    val losses=JSONArray()
                                                    lossRows.forEach{loss->losses.put(JSONObject().put("loss_date",oeeDate).put("shift",oeeShift).put("product_id",p.id).put("route_operation_id",op.id).put("machine_id",m.id).put("loss_category_id",loss.categoryId).put("duration_min",loss.duration.toDouble()).put("qty_loss",resolvedOeeLossQuantity(loss,oeeIdealCycleSeconds,oeeLossCategories)).put("remark",loss.remark))}
                                                    val payload=JSONObject().put("production_date",oeeDate).put("shift",oeeShift).put("product_id",p.id).put("route_operation_id",op.id).put("machine_id",m.id).put("operator_id",oeeOperatorId)
                                                        .put("shift_duration_min",oeeShiftMinutes.toDouble()).put("planned_break_min",oeeBreakMinutes.toDouble())
                                                        .put("downtime_min",availabilityLossTotal).put("good_count",oeeGoodCount.toDouble()).put("reject_count",oeeRejectCount.toDouble())
                                                        .put("ideal_cycle_time_sec",oeeIdealCycleSeconds ?: 0.0).put("remarks",oeeEntryRemarks)
                                                    if(oeeEntryId!=null) payload.put("downtime_min",availabilityLossTotal)
                                                    val saved=withContext(Dispatchers.IO){
                                                        ApiClient.saveOeeEntryWithLosses(payload,losses,auth,oeeEntryId,oeeEntryId?.let{oeeCorrectionReason.trim()})
                                                    }
                                                    val entry=saved.optJSONObject("entry")
                                                    val savedEntryId = entry?.optInt("id")?.takeIf { it > 0 } ?: oeeEntryId
                                                    val summaryGood=oeeGoodCount.toDoubleOrNull()?:0.0
                                                    val summaryReject=oeeRejectCount.toDoubleOrNull()?:0.0
                                                    val summaryTotal=summaryGood+summaryReject
                                                    val summaryPlanned=((oeeShiftMinutes.toDoubleOrNull()?:0.0)-(oeeBreakMinutes.toDoubleOrNull()?:0.0)).coerceAtLeast(0.0)
                                                    val summaryRun=(summaryPlanned-availabilityLossTotal).coerceAtLeast(0.0)
                                                    val summaryAvailability=if(summaryPlanned>0)summaryRun/summaryPlanned else 0.0
                                                    val summaryPerformance=if(summaryRun>0)((oeeIdealCycleSeconds?:0.0)*summaryTotal/60.0/summaryRun).coerceIn(0.0,1.0) else 0.0
                                                    val summaryQuality=if(summaryTotal>0)summaryGood/summaryTotal else 0.0
                                                    val summaryOee=summaryAvailability*summaryPerformance*summaryQuality
                                                    oeeSavedSummary=listOf(
                                                        if(savedEntryId!=null)"Production entry #$savedEntryId saved successfully." else "Production entry saved successfully.",
                                                        "OEE: ${"%.1f".format(summaryOee*100)}%",
                                                        "Availability: ${"%.1f".format(summaryAvailability*100)}%",
                                                        "Performance: ${"%.1f".format(summaryPerformance*100)}%",
                                                        "Quality: ${"%.1f".format(summaryQuality*100)}%",
                                                        "Good: ${summaryGood.toInt()}  •  Rejected: ${summaryReject.toInt()}  •  Total: ${summaryTotal.toInt()}",
                                                        "Availability loss: ${"%.1f".format(availabilityLossTotal)} min"
                                                    ).joinToString("\n")
                                                    // A successful correction must leave edit mode. Keeping the returned ID
                                                    // here made the form look as though the save had not completed.
                                                    oeeEntryId = null
                                                    oeeCorrectionReason = ""
                                                    oeeEntryLosses = listOf(OeeLossDraft())
                                                    // Keep the selected production scope and operator for quick consecutive entries,
                                                    // but clear record-specific values and return directly to the entry form.
                                                    oeeGoodCount = "0"
                                                    oeeRejectCount = "0"
                                                    oeeBreakMinutes = "0"
                                                    oeeEntryRemarks = ""
                                                    oeeCorrectionReason = ""
                                                    oeeMode = "ENTRY"
                                                    oeeError = null
                                                    oeeSuccess = if (savedEntryId != null) {
                                                        "Production entry #$savedEntryId saved successfully. Edit mode closed."
                                                    } else {
                                                        "Production entry saved successfully."
                                                    }
                                                    refreshOee(auth)
                                                } catch(e:Exception){oeeError=e.message ?: "Unable to save production entry and losses."}
                                                finally{oeeLoading=false}
                                            }
                                        },enabled=!oeeLoading,modifier=Modifier.fillMaxWidth().heightIn(min=54.dp),shape=RoundedCornerShape(13.dp)) { Text(if(oeeLoading)"SAVING PRODUCTION…" else if(oeeEntryId!=null)"SAVE CORRECTION" else "SAVE PRODUCTION ENTRY",fontWeight=FontWeight.Bold) }
                                        Text("Total production = good + rejected. Availability downtime is calculated from Availability-category loss events.",color=Muted,fontSize=10.sp)
                                    } else if(oeeMode=="MANAGEMENT") {
                                        SectionLabel("OEE management", "Period trend, machine ranking and classified loss Pareto")
                                        OutlinedTextField(oeeManagementFrom,{oeeManagementFrom=it},label={Text("From date (YYYY-MM-DD)")},modifier=Modifier.fillMaxWidth())
                                        Button(onClick={
                                            val auth=token
                                            if(auth!=null) scope.launch {
                                                oeeLoading=true;oeeError=null
                                                try{oeeManagement=withContext(Dispatchers.IO){ApiClient.loadOeeManagement(oeeManagementFrom,oeeDate,auth,oeeProduct?.id,oeeOperation?.id,oeeMachine?.id)}}
                                                catch(e:Exception){oeeError=e.message ?: "Unable to load OEE management summary."}
                                                finally{oeeLoading=false}
                                            }
                                        },enabled=!oeeLoading,modifier=Modifier.fillMaxWidth()){Text("LOAD MANAGEMENT SUMMARY")}
                                        oeeManagement?.let { mgmt ->
                                            val overall=mgmt.optJSONObject("overall")
                                            if(overall!=null) Text("Shift records: ${mgmt.optInt("entry_count")} • Loss events: ${mgmt.optInt("loss_event_count")} • Machines below target: ${mgmt.optInt("below_target_machine_count")}",color=Muted,fontSize=12.sp)
                                            SectionLabel("Machine ranking")
                                            val machineRows=mgmt.optJSONArray("machines") ?: JSONArray()
                                            for(i in 0 until minOf(machineRows.length(),8)){
                                                val row=machineRows.getJSONObject(i)
                                                Text("${row.optString("machine")}  •  ${"%.1f".format(row.optDouble("oee_reported")*100)}%  •  ${row.optString("status")}",color=if(row.optString("status")=="BELOW TARGET")Danger else Navy,fontSize=13.sp,fontWeight=FontWeight.SemiBold)
                                            }
                                            SectionLabel("Top loss categories")
                                            val pareto=mgmt.optJSONArray("loss_pareto") ?: JSONArray()
                                            for(i in 0 until minOf(pareto.length(),8)){
                                                val row=pareto.getJSONObject(i)
                                                Text("${row.optString("category")}  •  ${"%.1f".format(row.optDouble("minutes"))} min  •  ${row.optInt("events")} events",color=Navy,fontSize=13.sp)
                                            }
                                            SectionLabel("Daily OEE trend")
                                            val trend=mgmt.optJSONArray("trend") ?: JSONArray()
                                            for(i in 0 until trend.length()){
                                                val row=trend.getJSONObject(i)
                                                Text("${row.optString("date")}  •  OEE ${"%.1f".format(row.optDouble("oee_reported")*100)}%  (A ${"%.1f".format(row.optDouble("availability")*100)} / P ${"%.1f".format(row.optDouble("performance_raw")*100)} / Q ${"%.1f".format(row.optDouble("quality")*100)})",color=Muted,fontSize=11.sp)
                                            }
                                        }
                                    }
                                } else if(homeTab=="HISTORY") {
                                    ScreenTitle("Action history", selectedAction?.number ?: "Open an action to review its history")
                                    if(selectedAction==null) EmptyState("Select an action first","Open an action and choose VIEW ACTION HISTORY to see its updates.",{Icon(Icons.Filled.History,contentDescription=null,tint=Teal,modifier=Modifier.size(30.dp))})
                                    else {
                                        TextButton(onClick={homeTab="DETAIL"}){Text("← BACK TO ACTION DETAILS")}
                                        if(actionHistoryLoading) LinearProgressIndicator(Modifier.fillMaxWidth(),color=Teal)
                                        actionHistoryError?.let{Text(it,color=Danger,fontSize=12.sp)}
                                        if(!actionHistoryLoading && actionHistory.isEmpty() && actionHistoryError==null) EmptyState("No history entries yet","Progress updates and status changes will appear here.",{Icon(Icons.Filled.History,contentDescription=null,tint=Teal,modifier=Modifier.size(30.dp))})
                                        actionHistory.forEach { row ->
                                            Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(14.dp),colors=CardDefaults.cardColors(containerColor=Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border)) {
                                                Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(6.dp)) {
                                                    val changedByName=row.opt("changed_by_name")?.takeUnless{it==JSONObject.NULL}?.toString()?.trim().orEmpty()
                                                     val changedByUsername=row.opt("changed_by_username")?.takeUnless{it==JSONObject.NULL}?.toString()?.trim().orEmpty()
                                                     val actorName=changedByName.takeIf{it.isNotBlank()&&it!="null"}?:changedByUsername.takeIf{it.isNotBlank()&&it!="null"}?:"Unknown User"
                                                     Text(actorName,color=Navy,fontWeight=FontWeight.Bold,fontSize=14.sp)
                                                    Text(row.optString("changed_at").replace("T"," ").removeSuffix("Z"),color=Muted,fontSize=11.sp)
                                                    val oldStatus=row.optString("old_status");val newStatus=row.optString("new_status")
                                                    if(oldStatus.isNotBlank()||newStatus.isNotBlank()) Text(oldStatus.ifBlank{"—"}.replace("_"," ")+" → "+newStatus.ifBlank{"—"}.replace("_"," "),color=Teal,fontWeight=FontWeight.SemiBold,fontSize=12.sp)
                                                    val comment=row.optString("comment")
                                                    if(comment.isNotBlank()&&comment!="null") Text(comment,color=Navy,fontSize=13.sp)
                                                }
                                            }
                                        }
                                        if(actionAttachments.isNotEmpty()) {
                                            SectionLabel("Evidence attachments","Files linked to this action")
                                            actionAttachments.forEach { att ->
                                                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Color.White).padding(12.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                                                    Column(Modifier.weight(1f)) {
                                                        Text(att.optString("file_name"),color=Navy,fontWeight=FontWeight.SemiBold,fontSize=13.sp)
                                                        Text((att.optLong("size_bytes")/1024).toString()+" KB • "+att.optString("created_at").replace("T"," ").removeSuffix("Z"),color=Muted,fontSize=10.sp)
                                                    }
                                                    val context=LocalContext.current
                                                    OutlinedButton(onClick={
                                                        val auth=token
                                                        if(auth==null)message="Please sign in again."
                                                        else scope.launch {
                                                            busy=true
                                                            try {
                                                                val file=withContext(Dispatchers.IO){ApiClient.downloadActionAttachment(selectedAction!!.id,att.optInt("id"),att.optString("file_name"),cacheDir,auth)}
                                                                val uri=FileProvider.getUriForFile(context,context.packageName+".fileprovider",file)
                                                                val mime=att.optString("mime_type").ifBlank{"application/octet-stream"}
                                                                context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri,mime).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
                                                            } catch(e:Exception){message=e.message ?: "Unable to open attachment."}
                                                            finally{busy=false}
                                                        }
                                                    },enabled=!busy){Text("OPEN")}
                                                }
                                            }
                                        }
                                    }
                                } else if(homeTab=="ACCOUNT") {
                                    ScreenTitle("Account", "Your Production Review profile")
                                    Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(18.dp),colors=CardDefaults.cardColors(containerColor=Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border)) {
                                        Column(Modifier.padding(18.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
                                            Box(Modifier.size(56.dp).clip(RoundedCornerShape(17.dp)).background(Color(0xFFE7F1F8)),contentAlignment=Alignment.Center) {
                                                Icon(Icons.Filled.Person,contentDescription=null,tint=Navy,modifier=Modifier.size(32.dp))
                                            }
                                            Text(account?.fullName?.ifBlank { account?.username.orEmpty() }.orEmpty(),color=Navy,fontWeight=FontWeight.Bold,fontSize=19.sp)
                                            Divider(color=Border)
                                            SectionLabel("Username")
                                            Text(account?.username.orEmpty(),color=Navy,fontSize=14.sp)
                                            SectionLabel("Access role")
                                            StatusPill(account?.role.orEmpty().replace("_"," "), Teal)
                                            OutlinedButton(onClick={showLogoutConfirm=true},modifier=Modifier.fillMaxWidth().heightIn(min=50.dp),shape=RoundedCornerShape(12.dp)) { Text("LOG OUT") }
                                        }
                                    }
                                }
                                if(homeTab=="REJECTION") {
                                ScreenTitle("New rejection", "Capture a defect with process and quantity details")
                                Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(16.dp),colors=CardDefaults.cardColors(containerColor=Color.White),elevation=CardDefaults.cardElevation(2.dp)) {
                                    Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
                                        SectionLabel("Production details", "Date, shift, part and process information")
                                        OutlinedTextField(date,{date=it; product?.let{p->token?.let{t->refreshRoutes(p.id,it,t)}}},label={Text("Rejection date (YYYY-MM-DD)")},singleLine=true,modifier=Modifier.fillMaxWidth())
                                        ChoiceDropdown("Shift",listOf(Choice(1,"A"),Choice(2,"B"),Choice(3,"C"),Choice(4,"General")),null,{shift=it.label},shift)
                                        ChoiceDropdown("Product",masters?.products.orEmpty(),product,{selected ->
                                            product=selected
                                            rejectionTrend=emptyList()
                                            rejectionTrendError=null
                                            token?.let { auth ->
                                                refreshRoutes(selected.id,date,auth)
                                                refreshRejectionTrend(selected.id,auth)
                                            }
                                            detection=null
                                            responsible=null
                                        })
                                        if(product!=null) {
                                            RejectionQuantityTrend(
                                                productLabel=product!!.label,
                                                points=rejectionTrend,
                                                loading=rejectionTrendLoading,
                                                error=rejectionTrendError
                                            )
                                            ChoiceDropdown("Detection process",routes.map{Choice(it.id,it.label)},detection?.let{x->Choice(x.id,x.label)},{detection=RouteChoice(it.id,it.label)})
                                            ChoiceDropdown("Responsible process (optional)",routes.map{Choice(it.id,it.label)},responsible?.let{x->Choice(x.id,x.label)},{responsible=if(it.id<0)null else RouteChoice(it.id,it.label)},allowNone=true)
                                        }
                                        SectionLabel("Defect classification", "Identify the defect and where it was detected")
                                         ChoiceDropdown("Machine (optional)",masters?.machines.orEmpty(),machine,{machine=if(it.id<0)null else it},allowNone=true)
                                        ChoiceDropdown("Rejection phenomenon *",masters?.phenomena.orEmpty(),phenomenon,{phenomenon=it})
                                        SectionLabel("Quantity details", "Enter rejected, rework and scrap quantities")
                                         OutlinedTextField(rejectQty,{rejectQty=it},label={Text("Reject quantity *")},singleLine=true,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(reworkQty,{reworkQty=it},label={Text("Rework quantity")},singleLine=true,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(scrapQty,{scrapQty=it},label={Text("Scrap quantity")},singleLine=true,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(remark,{remark=it},label={Text("Remarks (optional)")},modifier=Modifier.fillMaxWidth(),minLines=2)
                                        Row(verticalAlignment=Alignment.CenterVertically) {
                                            Checkbox(actionRequired,{actionRequired=it})
                                            Text("Action required",color=Navy)
                                        }
                                        Divider(color=Border, thickness=1.dp)
                                        SectionLabel("Evidence photographs", "Capture clear overall and close-up views. Photos upload after the rejection is saved.")
                                        Text("Photos added: ${defectPhotos.size} / 5",color=Navy,fontWeight=FontWeight.SemiBold,fontSize=13.sp)
                                        OutlinedButton(
                                            onClick={
                                                if(defectPhotos.size>=5) message="Maximum 5 photographs per rejection."
                                                else try {
                                                    val photo=File.createTempFile("defect_${System.currentTimeMillis()}_", ".jpg", cacheDir)
                                                    pendingPhotoFile=photo
                                                    val uri=FileProvider.getUriForFile(this@MainActivity,"${packageName}.fileprovider",photo)
                                                    cameraLauncher.launch(uri)
                                                } catch(e:Exception) { message=e.message ?: "Unable to open camera." }
                                            },
                                            enabled=!busy && defectPhotos.size<5,
                                            modifier=Modifier.fillMaxWidth().heightIn(min=50.dp),
                                            shape=RoundedCornerShape(12.dp)
                                        ) { Text("TAKE DEFECT PHOTO") }
                                        defectPhotos.forEachIndexed { index, photo ->
                                            Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.SpaceBetween) {
                                                Text("Photo ${index+1} • ${(photo.length()/1024).coerceAtLeast(1)} KB",color=Muted,fontSize=12.sp)
                                                TextButton(onClick={photo.delete();defectPhotos.remove(photo)}) { Text("REMOVE") }
                                            }
                                        }
                                        if(savedRejectionId!=null && defectPhotos.isNotEmpty()) {
                                            OutlinedButton(
                                                onClick={
                                                    val auth=token
                                                    val recordId=savedRejectionId
                                                    if(auth!=null && recordId!=null) scope.launch {
                                                        busy=true
                                                        try {
                                                            defectPhotos.toList().forEach { photo ->
                                                                withContext(Dispatchers.IO){ApiClient.uploadRejectionPhoto(recordId,photo,auth)}
                                                                photo.delete()
                                                                defectPhotos.remove(photo)
                                                            }
                                                            resultMessage="Rejection #$recordId and all defect photographs uploaded successfully."
                                                            savedRejectionId=null
                                                        } catch(e:Exception) {
                                                            message="Rejection #$recordId is saved. Photo upload is still pending: ${e.message}"
                                                        } finally { busy=false }
                                                    }
                                                },
                                                enabled=!busy,
                                                modifier=Modifier.fillMaxWidth()
                                            ) { Text("RETRY PHOTO UPLOAD") }
                                        }
                                        Button(onClick={
                                            val auth=token
                                            val qty=rejectQty.toBigDecimalOrNull()
                                            val rework=reworkQty.toBigDecimalOrNull()
                                            val scrap=scrapQty.toBigDecimalOrNull()
                                            val selectedProduct=product
                                            val selectedDetection=detection
                                            val selectedPhenomenon=phenomenon
                                            when {
                                                auth==null -> message="Please sign in again."
                                                runCatching{LocalDate.parse(date)}.isFailure -> message="Enter a valid date as YYYY-MM-DD."
                                                selectedProduct==null -> message="Select a product."
                                                selectedDetection==null -> message="Select a detection process."
                                                selectedPhenomenon==null -> message="Rejection phenomenon is mandatory. Please select one before saving."
                                                qty==null||qty<=java.math.BigDecimal.ZERO -> message="Reject quantity must be greater than zero."
                                                rework==null||rework<java.math.BigDecimal.ZERO -> message="Enter a valid non-negative rework quantity."
                                                scrap==null||scrap<java.math.BigDecimal.ZERO -> message="Enter a valid non-negative scrap quantity."
                                                else -> {
                                                    val payload=JSONObject()
                                                        .put("rejection_date",date).put("shift",shift)
                                                        .put("product_id",selectedProduct.id)
                                                        .put("detection_route_operation_id",selectedDetection.id)
                                                        .put("phenomenon_id",selectedPhenomenon.id)
                                                        .put("reject_qty",qty.toPlainString())
                                                        .put("rework_qty",rework.toPlainString()).put("scrap_qty",scrap.toPlainString())
                                                        .put("action_required",actionRequired)
                                                    responsible?.let{payload.put("responsible_route_operation_id",it.id)}
                                                    machine?.let{payload.put("machine_id",it.id)}
                                                    if(remark.isNotBlank())payload.put("remark",remark.trim())
                                                    busy=true;message="Submitting rejection…";resultMessage=null
                                                    scope.launch {
                                                        try {
                                                            val saved=withContext(Dispatchers.IO){ApiClient.saveRejection(payload,auth)}
                                                            val id=saved.optInt("id")
                                                            val ppmPending=saved.optBoolean("ppm_pending")
                                                            // The server has confirmed the rejection. Reset the entry form immediately
                                                            // so the operator can clearly start the next record.
                                                            resetRejectionForm()
                                                            if(defectPhotos.isNotEmpty()) {
                                                                savedRejectionId=id
                                                                try {
                                                                    defectPhotos.toList().forEach { photo ->
                                                                        withContext(Dispatchers.IO){ApiClient.uploadRejectionPhoto(id,photo,auth)}
                                                                        photo.delete()
                                                                        defectPhotos.remove(photo)
                                                                    }
                                                                    savedRejectionId=null
                                                                    resultMessage="Rejection #$id saved with all defect photographs."
                                                                } catch(photoError:Exception) {
                                                                    resultMessage="Rejection #$id saved. Photo upload pending; use Retry Photo Upload."
                                                                    message=photoError.message ?: "Photo upload failed."
                                                                }
                                                            } else {
                                                                resultMessage=if(ppmPending)"Saved successfully • Record #$id • PPM pending production data." else "Saved successfully • Record #$id • PPM calculated by server."
                                                            }
                                                            message="Rejection record saved to Production Review."
                                                        }catch(e:Exception){message=e.message ?: "Submission failed. Check the server before retrying."}
                                                        finally{busy=false}
                                                    }
                                                }
                                            }
                                        },enabled=!busy && masters!=null,modifier=Modifier.fillMaxWidth().height(54.dp),colors=ButtonDefaults.buttonColors(containerColor=Teal),shape=RoundedCornerShape(12.dp),elevation=ButtonDefaults.buttonElevation(defaultElevation=2.dp)) { Text(if(busy)"PLEASE WAIT…" else "SAVE REJECTION",fontWeight=FontWeight.Bold,fontSize=14.sp) }
                                        resultMessage?.let {
                                            Card(colors=CardDefaults.cardColors(containerColor=Color(0xFFEAF6F2)),shape=RoundedCornerShape(12.dp),border=androidx.compose.foundation.BorderStroke(1.dp,Color(0xFFCBE8DD))) {
                                                Text(it,modifier=Modifier.fillMaxWidth().padding(12.dp),color=Success,fontWeight=FontWeight.SemiBold,fontSize=13.sp)
                                            }
                                        }
                                    }
                                }
                                }
                            }
                            Text("Secure access • Existing production records",color=Muted,fontSize=11.sp,modifier=Modifier.align(Alignment.CenterHorizontally))
                        }
                    }
                    if (account != null) {
                        NavigationBar(containerColor=Color.White, tonalElevation=10.dp, windowInsets = NavigationBarDefaults.windowInsets) {
                            bottomDestinations.forEach { destination ->
                                val selected = homeTab==destination || (destination=="ACTIONS" && homeTab in listOf("USER_ACTIONS","DETAIL"))
                                NavigationBarItem(
                                    selected=selected,
                                    onClick={
                                        if(destination=="MORE") scope.launch { drawerState.open() }
                                        else { homeTab=destination; if(destination=="ACTIONS") { selectedOwner=null; token?.let{refreshPendingActions(it)} } }
                                    },
                                    icon={ when(destination) { "ACTIONS"->Icon(Icons.Filled.Assignment,contentDescription=null); "REJECTION"->Icon(Icons.Filled.AssignmentLate,contentDescription=null); "OEE"->Icon(Icons.Filled.Speed,contentDescription=null); else->Icon(Icons.Filled.MoreHoriz,contentDescription=null) } },
                                    label={Text(when(destination) { "ACTIONS"->"Actions"; "REJECTION"->"Rejection"; "OEE"->"OEE"; else->"More" },maxLines=1)}
                                )
                            }
                        }
                    }
                    }
                }
                if (oeeError != null) {
                    AlertDialog(
                        onDismissRequest = { oeeError = null },
                        title = { Text("OEE needs attention", color=Navy, fontWeight=FontWeight.Bold) },
                        text = { Text(oeeError.orEmpty(), color=Navy) },
                        confirmButton = {
                            TextButton(onClick = { oeeError = null }) {
                                Text("OK", color=Teal, fontWeight=FontWeight.Bold)
                            }
                        },
                        dismissButton = {
                            if (oeeMachine != null && token != null && !oeeLoading) {
                                TextButton(onClick = {
                                    oeeError = null
                                    token?.let { refreshOee(it) }
                                }) { Text("REFRESH OEE", color=Teal) }
                            }
                        }
                    )
                }
                if (showLogoutConfirm) {
                    AlertDialog(
                        onDismissRequest={showLogoutConfirm=false},
                        title={Text("Log out?")},
                        text={Text("You will need to sign in again to access Production Review.")},
                        confirmButton={TextButton(onClick={
                            showLogoutConfirm=false
                            val old=token
                            scope.launch {
                                busy=true
                                try{if(old!=null)withContext(Dispatchers.IO){ApiClient.logout(old)}}catch(_:Exception){}
                                withContext(Dispatchers.IO){sessionStore.clear()}
                                token=null;account=null;masters=null;pendingActions=emptyList();pendingActionGroups=emptyList();selectedOwner=null;selectedAction=null;homeTab="ACTIONS";message="Signed out.";busy=false
                            }
                        }){Text("LOG OUT",color=Color(0xFFB3261E))}},
                        dismissButton={TextButton(onClick={showLogoutConfirm=false}){Text("CANCEL")}}
                    )
                }
            }
        }
    }
}
}


@Composable
private fun RejectionQuantityTrend(
    productLabel: String,
    points: List<RejectionTrendPoint>,
    loading: Boolean,
    error: String?
) {
    val today = LocalDate.now()
    val monthStart = today.withDayOfMonth(1)
    val monthEnd = today.withDayOfMonth(today.lengthOfMonth())
    val quantities = points.filter { !it.date.isAfter(today) }.associate { it.date.dayOfMonth to it.quantity }
    val total = quantities.values.sum()
    val maxValue = (quantities.values.maxOrNull() ?: 0f).coerceAtLeast(1f)
    val dayLabels = listOf(1, 5, 10, 15, 20, 25, monthEnd.dayOfMonth)

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFF8FAFC))
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Daily Rejection Quantity", color=Navy, fontWeight=FontWeight.Bold, fontSize=16.sp)
            Text("${monthStart.format(java.time.format.DateTimeFormatter.ofPattern("MMM yyyy"))} • ${productLabel}",
                color=Muted, fontSize=11.sp, maxLines=1)
            when {
                loading -> Text("Loading monthly rejection quantities…", color=Muted, fontSize=12.sp)
                error != null -> Text(error, color=Color(0xFFB3261E), fontSize=12.sp)
                else -> {
                    Text("Month total: ${total.toInt()}", color=Teal, fontWeight=FontWeight.SemiBold, fontSize=13.sp)
                    Canvas(Modifier.fillMaxWidth().height(145.dp)) {
                        val left = 4f
                        val right = size.width - 4f
                        val top = 8f
                        val bottom = size.height - 6f
                        val chartHeight = bottom - top
                        for (line in 0..3) {
                            val y = top + chartHeight * line / 3f
                            drawLine(Muted.copy(alpha=0.20f), Offset(left, y), Offset(right, y), strokeWidth=1f)
                        }
                        val count = monthEnd.dayOfMonth
                        val slot = (right - left) / count
                        val barWidth = (slot * 0.58f).coerceAtLeast(2f)
                        for (day in 1..count) {
                            if (day > today.dayOfMonth) continue
                            val value = (quantities[day] ?: 0f).coerceAtLeast(0f)
                            val barHeight = chartHeight * value / maxValue
                            if (barHeight > 0f) {
                                val x = left + (day - 1) * slot + (slot - barWidth) / 2f
                                drawRect(Teal, Offset(x, bottom - barHeight), Size(barWidth, barHeight))
                            }
                        }
                    }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement=Arrangement.SpaceBetween) {
                        dayLabels.distinct().forEach { day ->
                            Text(day.toString(), color=Muted, fontSize=10.sp)
                        }
                    }
                    if (total <= 0f) {
                        Text("No rejection quantity recorded for this part in the current month.", color=Muted, fontSize=11.sp)
                    }
                    Text("Daily reject quantity • future dates are not plotted", color=Muted, fontSize=10.sp)
                }
            }
        }
    }
}


@Composable
private fun ChoiceDropdown(
    label: String,
    choices: List<Choice>,
    selected: Choice?,
    onSelected: (Choice) -> Unit,
    selectedText: String? = null,
    allowNone: Boolean = false
) {
    var expanded by remember { mutableStateOf(false) }
    var search by remember { mutableStateOf("") }
    val filtered = remember(choices, search) {
        if (search.isBlank()) choices
        else choices.filter { it.label.contains(search.trim(), ignoreCase = true) }
    }

    Column {
        Text(label, color=Muted, fontSize=12.sp, fontWeight=FontWeight.Medium)
        OutlinedButton(
            onClick = { search = ""; expanded = true },
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(8.dp)
        ) {
            Text(
                selectedText ?: selected?.label ?: if (allowNone) "Not selected" else "Select…",
                modifier = Modifier.weight(1f),
                maxLines = 1
            )
            Text("⌕")
        }
    }

    if (expanded) {
        AlertDialog(
            onDismissRequest = { expanded = false },
            title = { Text("Select $label", color=Navy, fontWeight=FontWeight.Bold) },
            text = {
                Column(verticalArrangement=Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value=search,
                        onValueChange={search=it},
                        modifier=Modifier.fillMaxWidth(),
                        singleLine=true,
                        label={Text("Search")},
                        placeholder={Text("Type to filter…")}
                    )
                    Text("${filtered.size} item(s)", color=Muted, fontSize=12.sp)
                    LazyColumn(
                        modifier=Modifier.fillMaxWidth().heightIn(max=360.dp),
                        verticalArrangement=Arrangement.spacedBy(2.dp)
                    ) {
                        if (allowNone) {
                            item {
                                TextButton(
                                    onClick={onSelected(Choice(-1, "")); expanded=false},
                                    modifier=Modifier.fillMaxWidth()
                                ) { Text("Not selected", modifier=Modifier.fillMaxWidth()) }
                            }
                        }
                        items(filtered, key={it.id}) { item ->
                            TextButton(
                                onClick={onSelected(item); expanded=false},
                                modifier=Modifier.fillMaxWidth()
                            ) {
                                Text(
                                    item.label,
                                    modifier=Modifier.fillMaxWidth(),
                                    color=if (selected?.id == item.id) Teal else Navy
                                )
                            }
                        }
                        if (filtered.isEmpty()) {
                            item { Text("No matching items found.", color=Muted, modifier=Modifier.padding(12.dp)) }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick={expanded=false}) { Text("CLOSE") }
            },
            containerColor=Color.White
        )
    }
}
