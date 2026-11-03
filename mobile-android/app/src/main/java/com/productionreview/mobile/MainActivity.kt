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
    fun saveRejection(payload: JSONObject, token: String): JSONObject =
        request("/quality/daily", "POST", payload, token)

    fun uploadRejectionPhoto(rejectionId: Int, file: File, token: String): JSONObject {
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
                val header = "--$boundary\\r\\n" +
                    "Content-Disposition: form-data; name=\\"file\\"; filename=\\"${file.name}\\"\\r\\n" +
                    "Content-Type: image/jpeg\\r\\n\\r\\n"
                output.write(header.toByteArray(Charsets.UTF_8))
                file.inputStream().use { input -> input.copyTo(output) }
                output.write("\\r\\n--$boundary--\\r\\n".toByteArray(Charsets.UTF_8))
            }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) {
                val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull().orEmpty()
                throw IllegalStateException(detail.ifBlank { "Photo upload failed (HTTP $code)" })
            }
            return JSONObject(text)
        } finally { connection.disconnect() }
    }
}
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
                        token=saved; account=current; refreshMasters(saved)
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
                        Column(Modifier.fillMaxWidth().background(Navy).padding(horizontal=22.dp,vertical=20.dp)) {
                            Text("PRODUCTION REVIEW",color=Color(0xFFB9D5E5),fontSize=12.sp,fontWeight=FontWeight.Bold,letterSpacing=1.5.sp)
                            Spacer(Modifier.height(6.dp))
                            Text("Mobile Operations",color=Color.White,fontSize=25.sp,fontWeight=FontWeight.Bold)
                            Text("Shop-floor quality capture",color=Color(0xFFD7E2EC),fontSize=14.sp)
                        }
                        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp),verticalArrangement=Arrangement.spacedBy(14.dp)) {
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
                                                    token=result.first; account=result.second; password=""
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
                                        Text("Welcome, ${account!!.fullName.ifBlank{account!!.username}}",color=Navy,fontSize=18.sp,fontWeight=FontWeight.Bold)
                                        Text("Role: ${account!!.role}",color=Muted,fontSize=12.sp)
                                    }
                                    TextButton(onClick={
                                        val old=token
                                        scope.launch {
                                            busy=true
                                            try{if(old!=null)withContext(Dispatchers.IO){ApiClient.logout(old)}}catch(_:Exception){}
                                            withContext(Dispatchers.IO){sessionStore.clear()}
                                            token=null;account=null;masters=null;message="Signed out.";busy=false
                                        }
                                    },enabled=!busy){Text("SIGN OUT")}
                                }
                                Text("NEW REJECTION",color=Muted,fontSize=12.sp,fontWeight=FontWeight.Bold,letterSpacing=1.2.sp)
                                Card(Modifier.fillMaxWidth(),shape=RoundedCornerShape(16.dp),colors=CardDefaults.cardColors(containerColor=Color.White),elevation=CardDefaults.cardElevation(2.dp)) {
                                    Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
                                        Text("Rejection details",color=Navy,fontSize=20.sp,fontWeight=FontWeight.Bold)
                                        OutlinedTextField(date,{date=it; product?.let{p->token?.let{t->refreshRoutes(p.id,it,t)}}},label={Text("Rejection date (YYYY-MM-DD)")},singleLine=true,modifier=Modifier.fillMaxWidth())
                                        ChoiceDropdown("Shift",listOf(Choice(1,"A"),Choice(2,"B"),Choice(3,"C"),Choice(4,"General")),null,{shift=it.label},shift)
                                        ChoiceDropdown("Product",masters?.products.orEmpty(),product,{product=it;token?.let{t->refreshRoutes(it.id,date,t)};detection=null;responsible=null})
                                        if(product!=null) {
                                            ChoiceDropdown("Detection process",routes.map{Choice(it.id,it.label)},detection?.let{x->Choice(x.id,x.label)},{detection=RouteChoice(it.id,it.label)})
                                            ChoiceDropdown("Responsible process (optional)",routes.map{Choice(it.id,it.label)},responsible?.let{x->Choice(x.id,x.label)},{responsible=if(it.id<0)null else RouteChoice(it.id,it.label)},allowNone=true)
                                        }
                                        ChoiceDropdown("Machine (optional)",masters?.machines.orEmpty(),machine,{machine=if(it.id<0)null else it},allowNone=true)
                                        ChoiceDropdown("Rejection phenomenon",masters?.phenomena.orEmpty(),phenomenon,{phenomenon=it})
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
                                                selectedPhenomenon==null -> message="Select a rejection phenomenon."
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
                                                            rejectQty="";reworkQty="0";scrapQty="0";remark="";actionRequired=false
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
