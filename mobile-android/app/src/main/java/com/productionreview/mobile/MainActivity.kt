package com.productionreview.mobile

import android.os.Bundle
import android.net.Uri
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
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
private data class Masters(val products: List<Choice>, val machines: List<Choice>, val phenomena: List<Choice>)

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
            var selectedAction by remember { mutableStateOf<ActionItem?>(null) }
            var actionPlan by remember { mutableStateOf<JSONObject?>(null) }
            var followupComment by remember { mutableStateOf("") }
            var actionStatus by remember { mutableStateOf("IN_PROGRESS") }
            var why1 by remember { mutableStateOf("") }
            var why2 by remember { mutableStateOf("") }
            var rootCause by remember { mutableStateOf("") }
            var correctiveAction by remember { mutableStateOf("") }
            var preventiveAction by remember { mutableStateOf("") }
            var verificationMethod by remember { mutableStateOf("") }
            var verificationResult by remember { mutableStateOf("") }
            var evidenceFile by remember { mutableStateOf<File?>(null) }
            val evidencePicker=rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
                if(uri!=null) {
                    try {
                        val target=File(cacheDir,"action_evidence_${System.currentTimeMillis()}_${uri.lastPathSegment?.substringAfterLast('/')?.take(40) ?: "file"}")
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

            fun refreshPendingActions(auth:String) {
                scope.launch {
                    try { pendingActions=withContext(Dispatchers.IO){ApiClient.loadPendingActions(auth)} }
                    catch(e:Exception){ message="Unable to load pending actions: ${e.message}" }
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

            MaterialTheme(colorScheme=lightColorScheme(primary=Teal,secondary=Navy,background=Canvas,surface=Color.White)) {
                Surface(Modifier.fillMaxSize(),color=Canvas) {
                    Column(Modifier.fillMaxSize()) {
                        Column(Modifier.fillMaxWidth().background(Navy).padding(horizontal=18.dp,vertical=10.dp)) {
                            Text("PRODUCTION REVIEW",color=Color(0xFFB9D5E5),fontSize=10.sp,fontWeight=FontWeight.Bold,letterSpacing=1.2.sp)
                            Spacer(Modifier.height(2.dp))
                            Text("Mobile Operations",color=Color.White,fontSize=21.sp,fontWeight=FontWeight.Bold)
                            Text("Shop-floor quality capture",color=Color(0xFFD7E2EC),fontSize=12.sp)
                        }
                        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal=14.dp, vertical=10.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
                            if (account == null) {
                                Text("SECURE ACCESS",color=Muted,fontSize=12.sp,fontWeight=FontWeight.Bold,letterSpacing=1.2.sp)
                                Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(16.dp),colors=CardDefaults.cardColors(containerColor=Color.White)) {
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
                                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically) {
                                    Column {
                                        Text("Welcome, ${account!!.fullName.ifBlank{account!!.username}}",color=Navy,fontSize=15.sp,fontWeight=FontWeight.Bold,maxLines=1)
                                        Text("${account!!.role}",color=Muted,fontSize=10.sp)
                                    }
                                    TextButton(onClick={
                                        val old=token
                                        scope.launch {
                                            busy=true
                                            try{if(old!=null)withContext(Dispatchers.IO){ApiClient.logout(old)}}catch(_:Exception){}
                                            withContext(Dispatchers.IO){sessionStore.clear()}
                                            token=null;account=null;masters=null;message="Signed out.";busy=false
                                        }
                                    },enabled=!busy){Text("LOG OUT",fontSize=11.sp,fontWeight=FontWeight.Bold)}
                                }
                                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                                    FilterChip(selected=homeTab=="ACTIONS",onClick={homeTab="ACTIONS";token?.let{refreshPendingActions(it)}},label={Text("PENDING ACTIONS")})
                                    FilterChip(selected=homeTab=="REJECTION",onClick={homeTab="REJECTION"},label={Text("NEW REJECTION")})
                                }
                                if(homeTab=="ACTIONS") {
                                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween,verticalAlignment=Alignment.CenterVertically) {
                                        Text("My pending actions",color=Navy,fontSize=19.sp,fontWeight=FontWeight.Bold)
                                        Text("${pendingActions.size} open",color=Muted,fontSize=12.sp)
                                    }
                                    if(pendingActions.isEmpty()) Text("No pending actions assigned to you.",color=Muted)
                                    pendingActions.forEach { item ->
                                        Card(Modifier.fillMaxWidth().clickable { token?.let{openAction(item,it)} },colors=CardDefaults.cardColors(containerColor=Color.White)) {
                                            Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(5.dp)) {
                                                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
                                                    Text(item.number,color=Navy,fontWeight=FontWeight.Bold)
                                                    Text(if(item.overdue)"OVERDUE" else item.status.replace("_"," "),color=if(item.overdue)Color(0xFFB3261E) else Teal,fontWeight=FontWeight.Bold,fontSize=11.sp)
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
                                    TextButton(onClick={homeTab="ACTIONS";token?.let{refreshPendingActions(it)}}){Text("← BACK TO PENDING ACTIONS")}
                                    Text(item.number,color=Navy,fontSize=20.sp,fontWeight=FontWeight.Bold)
                                    Text(item.description,color=Muted)
                                    Text(if(item.whyWhy)"WHY-WHY ESCALATION" else "ACTION REQUIRED",color=Teal,fontWeight=FontWeight.Bold)
                                    OutlinedTextField(followupComment,{followupComment=it},label={Text("Action taken / progress update *")},modifier=Modifier.fillMaxWidth(),minLines=3)
                                    OutlinedButton(onClick={evidencePicker.launch("*/*")},enabled=!busy,modifier=Modifier.fillMaxWidth()) { Text(if(evidenceFile==null)"ADD EVIDENCE PHOTO / DOCUMENT" else "CHANGE EVIDENCE FILE") }
                                    evidenceFile?.let { Text("Selected: ${it.name} • ${(it.length()/1024).coerceAtLeast(1)} KB",color=Muted,fontSize=12.sp) }
                                    Text("Update status",color=Muted,fontSize=12.sp)
                                    Row(horizontalArrangement=Arrangement.spacedBy(6.dp)) {
                                        listOf("OPEN","IN_PROGRESS","BLOCKED").forEach { st -> FilterChip(selected=actionStatus==st,onClick={actionStatus=st},label={Text(st.replace("_"," "))}) }
                                    }
                                    if(item.whyWhy) {
                                        Text("Why-Why investigation",color=Navy,fontWeight=FontWeight.Bold)
                                        OutlinedTextField(why1,{why1=it},label={Text("Why 1")},modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(why2,{why2=it},label={Text("Why 2")},modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(rootCause,{rootCause=it},label={Text("Root cause")},modifier=Modifier.fillMaxWidth(),minLines=2)
                                        OutlinedTextField(correctiveAction,{correctiveAction=it},label={Text("Corrective action")},modifier=Modifier.fillMaxWidth(),minLines=2)
                                        OutlinedTextField(preventiveAction,{preventiveAction=it},label={Text("Preventive action")},modifier=Modifier.fillMaxWidth(),minLines=2)
                                        OutlinedTextField(verificationMethod,{verificationMethod=it},label={Text("Verification method")},modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(verificationResult,{verificationResult=it},label={Text("Verification result")},modifier=Modifier.fillMaxWidth())
                                        Text("Why-Why completion: ${item.completion}%",color=Muted,fontSize=12.sp)
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
                                                    val plan=JSONObject().put("why1",why1).put("why2",why2).put("root_cause",rootCause).put("corrective_action",correctiveAction).put("preventive_action",preventiveAction).put("verification_method",verificationMethod).put("verification_result",verificationResult)
                                                    withContext(Dispatchers.IO){ApiClient.updateWhyWhy(item.id,plan,auth)}
                                                }
                                                message="Action update submitted successfully."
                                                selectedAction=null;homeTab="ACTIONS";refreshPendingActions(auth)
                                            } catch(e:Exception){message=e.message ?: "Unable to submit action update."}
                                            finally{busy=false}
                                        }
                                    },enabled=!busy,modifier=Modifier.fillMaxWidth()) { Text(if(busy)"SAVING…" else "SUBMIT ACTION UPDATE") }
                                }
                                if(homeTab=="REJECTION") {
                                Text("NEW REJECTION",color=Muted,fontSize=12.sp,fontWeight=FontWeight.Bold,letterSpacing=1.2.sp)
                                Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(16.dp),colors=CardDefaults.cardColors(containerColor=Color.White),elevation=CardDefaults.cardElevation(2.dp)) {
                                    Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
                                        Text("Rejection details",color=Navy,fontSize=20.sp,fontWeight=FontWeight.Bold)
                                        OutlinedTextField(date,{date=it; product?.let{p->token?.let{t->refreshRoutes(p.id,it,t)}}},label={Text("Rejection date (YYYY-MM-DD)")},singleLine=true,modifier=Modifier.fillMaxWidth())
                                        ChoiceDropdown("Shift",listOf(Choice(1,"A"),Choice(2,"B"),Choice(3,"C"),Choice(4,"General")),null,{shift=it.label},shift)
                                        ChoiceDropdown("Product",masters?.products.orEmpty(),product,{product=it;token?.let{t->refreshRoutes(it.id,date,t)};detection=null;responsible=null})
                                        if(product!=null) {
                                            ChoiceDropdown("Detection process",routes.map{Choice(it.id,it.label)},detection?.let{x->Choice(x.id,x.label)},{detection=RouteChoice(it.id,it.label)})
                                            ChoiceDropdown("Responsible process (optional)",routes.map{Choice(it.id,it.label)},responsible?.let{x->Choice(x.id,x.label)},{responsible=if(it.id<0)null else RouteChoice(it.id,it.label)},allowNone=true)
                                        }
                                        ChoiceDropdown("Machine (optional)",masters?.machines.orEmpty(),machine,{machine=if(it.id<0)null else it},allowNone=true)
                                        ChoiceDropdown("Rejection phenomenon *",masters?.phenomena.orEmpty(),phenomenon,{phenomenon=it})
                                        OutlinedTextField(rejectQty,{rejectQty=it},label={Text("Reject quantity *")},singleLine=true,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(reworkQty,{reworkQty=it},label={Text("Rework quantity")},singleLine=true,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(scrapQty,{scrapQty=it},label={Text("Scrap quantity")},singleLine=true,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
                                        OutlinedTextField(remark,{remark=it},label={Text("Remarks (optional)")},modifier=Modifier.fillMaxWidth(),minLines=2)
                                        Row(verticalAlignment=Alignment.CenterVertically) {
                                            Checkbox(actionRequired,{actionRequired=it})
                                            Text("Action required",color=Navy)
                                        }
                                        Divider()
                                        Text("Defect photographs (${defectPhotos.size}/5)",color=Navy,fontWeight=FontWeight.SemiBold)
                                        Text("Capture clear overall and close-up views. Photos upload after the rejection is saved.",color=Muted,fontSize=12.sp)
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
                                            modifier=Modifier.fillMaxWidth()
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
                                        },enabled=!busy && masters!=null,modifier=Modifier.fillMaxWidth().height(52.dp),colors=ButtonDefaults.buttonColors(containerColor=Teal),shape=RoundedCornerShape(10.dp)) { Text(if(busy)"PLEASE WAIT…" else "SAVE REJECTION",fontWeight=FontWeight.Bold) }
                                        resultMessage?.let{Text(it,color=Teal,fontWeight=FontWeight.SemiBold)}
                                    }
                                }
                                }
                            }
                            Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(16.dp),colors=CardDefaults.cardColors(containerColor=Color.White)) {
                                Column(Modifier.padding(16.dp)) {
                                    Text("Connection",color=Navy,fontSize=16.sp,fontWeight=FontWeight.Bold)
                                    Text(message,color=Muted,fontSize=14.sp)
                                    Text("machineshop.duckdns.org • HTTPS",color=Teal,fontSize=12.sp,fontWeight=FontWeight.Medium)
                                }
                            }
                            Text("Secure access • Existing production records",color=Muted,fontSize=11.sp,modifier=Modifier.align(Alignment.CenterHorizontally))
                        }
                    }
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
