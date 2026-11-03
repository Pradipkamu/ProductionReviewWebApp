package com.productionreview.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val Navy = Color(0xFF142B45)
private val Teal = Color(0xFF087F8C)
private val Canvas = Color(0xFFF2F5F8)
private val Muted = Color(0xFF627386)

class MainActivity : ComponentActivity() {
 override fun onCreate(savedInstanceState: Bundle?) {
  super.onCreate(savedInstanceState)
  setContent {
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
       Text("QUICK ENTRY", color=Muted, fontSize=12.sp, fontWeight=FontWeight.Bold, letterSpacing=1.2.sp)
       Card(Modifier.fillMaxWidth(), shape=RoundedCornerShape(16.dp), colors=CardDefaults.cardColors(containerColor=Color.White), elevation=CardDefaults.cardElevation(2.dp)) {
        Column(Modifier.padding(18.dp)) {
         Text("Rejection Entry", color=Navy, fontSize=20.sp, fontWeight=FontWeight.Bold)
         Spacer(Modifier.height(6.dp))
         Text("Record a quality rejection using your existing production account.", color=Muted, fontSize=14.sp, lineHeight=20.sp)
         Spacer(Modifier.height(16.dp))
         Button(onClick={}, modifier=Modifier.fillMaxWidth().height(52.dp), shape=RoundedCornerShape(10.dp), colors=ButtonDefaults.buttonColors(containerColor=Teal)) {
          Text("NEW REJECTION", fontWeight=FontWeight.Bold, letterSpacing=0.5.sp)
         }
        }
       }
       Card(Modifier.fillMaxWidth(), shape=RoundedCornerShape(16.dp), colors=CardDefaults.cardColors(containerColor=Color.White)) {
        Column(Modifier.padding(18.dp)) {
         Text("Connection", color=Navy, fontSize=16.sp, fontWeight=FontWeight.Bold)
         Spacer(Modifier.height(5.dp))
         Row(verticalAlignment=Alignment.CenterVertically) {
          Text("●", color=Teal, fontSize=13.sp)
          Text("  API connection will be configured", color=Muted, fontSize=13.sp)
         }
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
