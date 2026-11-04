package com.productionreview.mobile

import android.os.Bundle
import android.net.Uri
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import androidx.compose.foundation.background
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.time.LocalDate

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

private object ApiClient {
    private fun requestText(path: String, method: String, body: JSONObject? = null, token: String? = null): String {
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
        }
        try {
            if (body != null) connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) {
                val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull().orEmpty()
                throw IllegalStateException(detail.ifBlank { "Server returned HTTP $code" })
            }
            return text
        } finally { connection.disconnect() }
    }

    private fun request(path: String, method: String, body: JSONObject? = null, token: String? = null): JSONObject =
        JSONObject(requestText(path, method, body, token))

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
                val list=(0 until ops.length()).map { j ->
                    val op=ops.getJSONObject(j)
                    RouteChoice(op.getInt("route_operation_id"), "${op.optInt("sequence_no")}. ${op.optString("operation")}")
                }
                candidates.add(from to list)
            }
        }
        return candidates.maxByOrNull { it.first }?.second ?: emptyList()
    }
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
private fun MetricTile(label: String, value: String, accent: Color, modifier: Modifier = Modifier) {
    Card(modifier = modifier, shape = RoundedCornerShape(14.dp), colors = CardDefaults.cardColors(containerColor = Color.White),
        border = androidx.compose.foundation.BorderStroke(1.dp, Border), elevation = CardDefaults.cardElevation(1.dp)) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 13.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Box(Modifier.width(28.dp).height(3.dp).clip(RoundedCornerShape(3.dp)).background(accent))
            Text(value, color = Navy, fontSize = 23.sp, fontWeight = FontWeight.Bold)
            Text(label, color = Muted, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, maxLines = 2)
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
            val scope = rememberCoroutineScope()
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
                                Text(if (account == null) "Mobile Operations" else when(homeTab) { "ACTIONS"->"Pending Actions"; "USER_ACTIONS"->"User Actions"; "DETAIL"->"Action Details"; "REJECTION"->"Rejection Entry"; "OEE"->"OEE"; "HISTORY"->"Action History"; "ACCOUNT"->"Account"; else->"Mobile Operations" },color=Color.White,fontSize=19.sp,fontWeight=FontWeight.Bold)
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
                                                } catch(e:Exception){message=e.message ?: "Unable to sign in."}
                                                finally{busy=false}
                                            }}
                                        },enabled=!busy,modifier=Modifier.fillMaxWidth().height(50.dp),colors=ButtonDefaults.buttonColors(containerColor=Teal)) { Text(if(busy)"PLEASE WAIT…" else "SIGN IN") }
                                    }
                                }
                            } else {
                                Card(modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp), colors = CardDefaults.cardColors(containerColor = Color.White), border = androidx.compose.foundation.BorderStroke(1.dp, Border)) {
                                    Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                            Text("Welcome back", color = Muted, fontSize = 12.sp)
                                            Text(account!!.fullName.ifBlank { account!!.username }, color = Navy, fontSize = 17.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                                            Text(account!!.role.replace("_", " "), color = Teal, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                                        }
                                        Box(Modifier.size(42.dp).clip(RoundedCornerShape(14.dp)).background(Color(0xFFE7F1F8)), contentAlignment = Alignment.Center) {
                                            Icon(Icons.Filled.Person, contentDescription = null, tint = Navy, modifier = Modifier.size(24.dp))
                                        }
                                    }
                                }
                                val isManager = account!!.role.uppercase() in listOf("ADMIN", "MANAGEMENT")
                                val totalOpen = if (isManager) pendingActionGroups.sumOf { it.openCount } else pendingActions.size
                                val totalOverdue = if (isManager) pendingActionGroups.sumOf { it.overdueCount } else pendingActions.count { it.overdue }
                                val dueToday = if (isManager) pendingActionGroups.sumOf { it.dueTodayCount } else pendingActions.count { it.due.substringBefore("T") == LocalDate.now().toString() }
                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    MetricTile("OPEN ACTIONS", totalOpen.toString(), Teal, Modifier.weight(1f))
                                    MetricTile("OVERDUE", totalOverdue.toString(), Danger, Modifier.weight(1f))
                                    MetricTile("DUE TODAY", dueToday.toString(), Warning, Modifier.weight(1f))
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
                                            try {
                                                withContext(Dispatchers.IO){ApiClient.updateAction(item.id,followupComment.trim(),actionStatus,auth)}
                                                evidenceFile?.let { evidence ->
                                                    withContext(Dispatchers.IO){ApiClient.uploadActionEvidence(item.id,evidence,auth)}
                                                    evidence.delete();evidenceFile=null
                                                }
                                                if(item.whyWhy) {
                                                    val plan=JSONObject().put("why1",why1).put("why2",why2).put("why3",why3).put("why4",why4).put("why5",why5).put("root_cause",rootCause).put("corrective_action",correctiveAction).put("preventive_action",preventiveAction).put("verification_method",verificationMethod).put("verification_result",verificationResult)
                                                    withContext(Dispatchers.IO){ApiClient.updateWhyWhy(item.id,plan,auth)}
                                                }
                                                message="Action update submitted successfully."
                                                selectedAction=null;homeTab="ACTIONS";refreshPendingActions(auth)
                                            } catch(e:Exception){message=e.message ?: "Unable to submit action update."}
                                            finally{busy=false}
                                        }
                                    },enabled=!busy,modifier=Modifier.fillMaxWidth()) { Text(if(busy)"SAVING…" else "SUBMIT ACTION UPDATE") }
                                }
                                if(homeTab=="OEE") {
                                    ScreenTitle("OEE", "Machine effectiveness and production performance")
                                    Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(18.dp),colors=CardDefaults.cardColors(containerColor=Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border)) {
                                        Column(Modifier.padding(20.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
                                            Box(Modifier.size(52.dp).clip(RoundedCornerShape(15.dp)).background(Color(0xFFE6F2F4)),contentAlignment=Alignment.Center) { Icon(Icons.Filled.Speed,contentDescription=null,tint=Teal,modifier=Modifier.size(30.dp)) }
                                            Text("OEE mobile dashboard",color=Navy,fontSize=18.sp,fontWeight=FontWeight.Bold)
                                            Text("The screen is prepared for machine availability, performance, quality and overall equipment effectiveness indicators.",color=Muted,fontSize=14.sp)
                                            Divider(color=Border)
                                            StatusPill("LIVE DATA CONNECTION PENDING", Warning)
                                            Text("No production figures are simulated. Values will appear after the authorized API and role permissions are connected.",color=Muted,fontSize=12.sp)
                                        }
                                    }
                                } else if(homeTab=="HISTORY") {
                                    ScreenTitle("Action history", "Review previous action updates")
                                    Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(18.dp),colors=CardDefaults.cardColors(containerColor=Color.White),border=androidx.compose.foundation.BorderStroke(1.dp,Border)) {
                                        Column(Modifier.fillMaxWidth().padding(20.dp),horizontalAlignment=Alignment.CenterHorizontally,verticalArrangement=Arrangement.spacedBy(9.dp)) {
                                            Box(Modifier.size(52.dp).clip(RoundedCornerShape(15.dp)).background(Color(0xFFE7F1F8)),contentAlignment=Alignment.Center) { Icon(Icons.Filled.History,contentDescription=null,tint=Navy,modifier=Modifier.size(30.dp)) }
                                            Text("History module not connected",color=Navy,fontSize=16.sp,fontWeight=FontWeight.Bold)
                                            Text("The action history API is not yet connected to this mobile screen. No records are simulated or hidden.",color=Muted,fontSize=13.sp,textAlign=androidx.compose.ui.text.style.TextAlign.Center)
                                            StatusPill("AWAITING API INTEGRATION", Warning)
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
