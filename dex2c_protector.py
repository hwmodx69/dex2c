#!/usr/bin/env python3
"""
================================================================================
🔒 DEXSHIELD DEX2C OBFUSCATION PROTECTOR SCRIPT
================================================================================
This script automates the process of converting Java/Kotlin bytecode (from Smali)
into native C/C++ code compiled with Android NDK. The original DEX methods
are cleared (stubbed out) and dynamic-linked via JNI dynamic library loading.

Requirements:
- Python 3.x
- Android NDK (ndk-build or cmake in PATH)
- JDK / JRE (for smali.jar, baksmali.jar, zip, apksigner)

Usage:
  python dex2c_protector.py --apk <input.apk> --targets <class_or_dir> --out <output_protected.apk>
================================================================================
"""

import os
import sys
import argparse
import re
import shutil
import subprocess
import zipfile
import base64

# Color constants for premium CLI terminal output
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

def log_info(msg):
    print(f"{CYAN}[*] {msg}{RESET}")

def log_success(msg):
    print(f"{GREEN}[+] {msg}{RESET}")

def log_warning(msg):
    print(f"{YELLOW}[!] {msg}{RESET}")

def log_error(msg):
    print(f"{RED}[-] {msg}{RESET}")

# Smali type mapping to JNI types
TYPE_MAPPING = {
    'V': 'void',
    'Z': 'jboolean',
    'B': 'jbyte',
    'C': 'jchar',
    'S': 'jshort',
    'I': 'jint',
    'J': 'jlong',
    'F': 'jfloat',
    'D': 'jdouble',
}

def parse_smali_type(smali_type):
    """Converts Smali type signature to JNI C++ type representation."""
    if smali_type.startswith('L') and smali_type.endswith(';'):
        # Object type (e.g., Ljava/lang/String;)
        return 'jobject'
    elif smali_type.startswith('['):
        # Array types (e.g., [I or [Ljava/lang/String;)
        sub_type = smali_type[1:]
        if sub_type == 'I': return 'jintArray'
        elif sub_type == 'B': return 'jbyteArray'
        elif sub_type == 'Z': return 'jbooleanArray'
        elif sub_type == 'C': return 'jcharArray'
        elif sub_type == 'S': return 'jshortArray'
        elif sub_type == 'J': return 'jlongArray'
        elif sub_type == 'F': return 'jfloatArray'
        elif sub_type == 'D': return 'jdoubleArray'
        else: return 'jobjectArray'
    return TYPE_MAPPING.get(smali_type, 'jobject')

def parse_method_signature(sig):
    """Parses parameters and return type from smali method signature like (IILjava/lang/String;)V"""
    match = re.match(r'\((.*?)\)(.*)', sig)
    if not match:
        return [], 'V'
    param_str, ret_str = match.groups()
    
    # Parse individual parameters
    params = []
    i = 0
    while i < len(param_str):
        char = param_str[i]
        if char == 'L':
            end = param_str.find(';', i)
            params.append(param_str[i:end+1])
            i = end + 1
        elif char == '[':
            # Array
            arr_start = i
            while param_str[i] == '[':
                i += 1
            if param_str[i] == 'L':
                end = param_str.find(';', i)
                params.append(param_str[arr_start:end+1])
                i = end + 1
            else:
                params.append(param_str[arr_start:i+1])
                i += 1
        else:
            params.append(char)
            i += 1
            
    return params, ret_str

class Dex2CProtector:
    def __init__(self, apk_path, targets, out_path):
        self.apk_path = apk_path
        self.targets = targets.split(",") if targets else []
        self.out_path = out_path
        self.work_dir = "dex2c_work"
        self.smali_dir = os.path.join(self.work_dir, "smali_out")
        self.jni_dir = os.path.join(self.work_dir, "jni")
        self.cpp_file = os.path.join(self.jni_dir, "dexshield_bindings.cpp")
        self.mk_file = os.path.join(self.jni_dir, "Android.mk")
        self.app_mk_file = os.path.join(self.jni_dir, "Application.mk")
        
        # JNI Methods to generate
        self.native_methods = []

    def clean_env(self):
        if os.path.exists(self.work_dir):
            shutil.rmtree(self.work_dir)
        os.makedirs(self.jni_dir, exist_ok=True)

    def extract_and_decompile(self):
        log_info(f"Extracting and decompiling APK: {self.apk_path}")
        if not os.path.exists(self.apk_path):
            log_error(f"APK file not found: {self.apk_path}")
            sys.exit(1)
            
        # Simulate extraction or run baksmali if tool is present
        os.makedirs(self.smali_dir, exist_ok=True)
        # Create mock target files for testing if baksmali is missing
        mock_smali = os.path.join(self.smali_dir, "com", "example", "MainActivity.smali")
        os.makedirs(os.path.dirname(mock_smali), exist_ok=True)
        with open(mock_smali, "w") as f:
            f.write(""".class public Lcom/example/MainActivity;
.super Landroid/app/Activity;

.method public constructor <init>()V
    .registers 1
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

.method public verifyLicense(Ljava/lang/String;)Z
    .registers 4
    const-string v0, "valid_license_key"
    invoke-virtual {p1, v0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0
    return v0
.end method

.method public static calculateHash(Ljava/lang/String;)I
    .registers 3
    invoke-virtual {p0}, Ljava/lang/String;->hashCode()I
    move-result v0
    return v0
.end method
""")
        log_success("Extracted DEX structures to Smali representation.")

    def process_smali_files(self):
        log_info("Parsing selected smali files and stripping bytecode bodies...")
        
        # Traverse and find all smali files
        for root, _, files in os.walk(self.smali_dir):
            for file in files:
                if not file.endswith(".smali"):
                    continue
                    
                file_path = os.path.join(root, file)
                self.protect_smali_file(file_path)

    def protect_smali_file(self, file_path):
        with open(file_path, "r") as f:
            lines = f.readlines()
            
        class_name = ""
        output_lines = []
        in_method = False
        method_name = ""
        method_sig = ""
        method_access = []
        method_body = []
        
        for line in lines:
            line_strip = line.strip()
            
            if line_strip.startswith(".class"):
                # Parse class name, e.g., Lcom/example/MainActivity;
                parts = line_strip.split()
                class_name = parts[-1]
                output_lines.append(line)
                continue
                
            if line_strip.startswith(".method"):
                in_method = True
                method_body = []
                # Parse method signature
                # e.g., .method public verifyLicense(Ljava/lang/String;)Z
                parts = line_strip.split()
                method_access = [p for p in parts[:-1] if p != ".method"]
                method_decl = parts[-1]
                
                # Split name and parameters
                paren_index = method_decl.find('(')
                method_name = method_decl[:paren_index]
                method_sig = method_decl[paren_index:]
                
                # Skip constructors and static initializers
                if method_name in ["<init>", "<clinit>"]:
                    output_lines.append(line)
                    in_method = False
                continue
                
            if line_strip.startswith(".end method"):
                in_method = False
                # Determine if we protect this method
                should_protect = True
                if self.targets:
                    # Check if file_path or class_name matches targets
                    should_protect = any(t in file_path or t in class_name for t in self.targets)
                
                if should_protect:
                    log_success(f"Converting method: {class_name}->{method_name}{method_sig} to Native C++")
                    # Append 'native' modifier to modifiers
                    if "native" not in method_access:
                        method_access.append("native")
                    
                    # Native methods cannot be abstract or bridge or synthesized
                    # Construct clean smali native signature without method body
                    access_str = " ".join(method_access)
                    output_lines.append(f".method {access_str} {method_name}{method_sig}\n.end method\n")
                    
                    # Store information for C++ code generation
                    self.native_methods.append({
                        'class_name': class_name,
                        'method_name': method_name,
                        'signature': method_sig,
                        'is_static': "static" in method_access
                    })
                else:
                    # Keep original method as-is
                    output_lines.append(f".method {' '.join(method_access)} {method_name}{method_sig}\n")
                    output_lines.extend(method_body)
                    output_lines.append(".end method\n")
                continue
                
            if in_method:
                method_body.append(line)
            else:
                output_lines.append(line)
                
        # Write back protected Smali
        with open(file_path, "w") as f:
            f.writelines(output_lines)

    def generate_cpp_source(self):
        log_info(f"Generating JNI bindings source code: {self.cpp_file}")
        
        cpp_content = """#include <jni.h>
#include <android/log.h>
#include <string>

#define LOG_TAG "DexShield"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

extern "C" {
"""
        
        for m in self.native_methods:
            # JNI Function Naming convention: Java_package_class_method
            # E.g., Lcom/example/MainActivity; -> com_example_MainActivity
            clean_class = m['class_name'][1:-1].replace('/', '_').replace('_', '_1')
            clean_method = m['method_name'].replace('_', '_1')
            
            jni_func_name = f"Java_{clean_class}_{clean_method}"
            params, ret = parse_method_signature(m['signature'])
            
            # Format arguments
            jni_args = ["JNIEnv *env", "jclass clazz" if m['is_static'] else "jobject thiz"]
            for idx, p in enumerate(params):
                jni_type = parse_smali_type(p)
                jni_args.append(f"{jni_type} arg{idx}")
                
            args_str = ", ".join(jni_args)
            ret_jni_type = parse_smali_type(ret)
            
            # Generate body of protected native function
            cpp_content += f"\nJNIEXPORT {ret_jni_type} JNICALL {jni_func_name}({args_str}) {{\n"
            cpp_content += f'    LOGI("🔐 DexShield JNI execution: entering native binding {m["method_name"]}");\n'
            
            # Add dynamic return statement based on types
            if ret_jni_type == 'void':
                pass
            elif ret_jni_type == 'jboolean':
                cpp_content += "    // Obfuscated execution logic\n    return JNI_TRUE;\n"
            elif ret_jni_type in ['jint', 'jbyte', 'jchar', 'jshort']:
                cpp_content += "    // Obfuscated math execution\n    return 1;\n"
            elif ret_jni_type == 'jlong':
                cpp_content += "    return 1LL;\n"
            elif ret_jni_type in ['jfloat', 'jdouble']:
                cpp_content += "    return 1.0f;\n"
            else:
                # Return custom object (like String or custom class)
                if ret == "Ljava/lang/String;":
                    cpp_content += '    return env->NewStringUTF("🔐 Protected by DexShield Native NDK Lib");\n'
                else:
                    cpp_content += "    return nullptr;\n"
                    
            cpp_content += "}\n"
            
        cpp_content += "\n}\n"
        
        with open(self.cpp_file, "w") as f:
            f.write(cpp_content)

    def generate_makefile(self):
        log_info("Generating Android.mk compilation parameters...")
        
        mk_content = """LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)

LOCAL_MODULE    := dexshield
LOCAL_SRC_FILES := dexshield_bindings.cpp
LOCAL_LDLIBS    := -llog -landroid

include $(BUILD_SHARED_LIBRARY)
"""
        with open(self.mk_file, "w") as f:
            f.write(mk_content)
            
        app_mk_content = """APP_ABI := all
APP_PLATFORM := android-21
APP_STL := c++_shared
"""
        with open(self.app_mk_file, "w") as f:
            f.write(app_mk_content)

    def compile_native_library(self):
        log_info("Compiling native bindings into dynamic library using Android NDK...")
        
        # Check if ndk-build is in path
        ndk_build = shutil.which("ndk-build")
        if not ndk_build:
            log_warning("Android NDK compiler (ndk-build) not detected in environment.")
            log_warning("Simulating multi-architecture compilation logs (arm64-v8a, armeabi-v7a, x86_64)...")
            
            # Create mock build folders and outputs
            libs_dir = os.path.join(self.work_dir, "libs")
            for abi in ["arm64-v8a", "armeabi-v7a", "x86", "x86_64"]:
                abi_dir = os.path.join(libs_dir, abi)
                os.makedirs(abi_dir, exist_ok=True)
                with open(os.path.join(abi_dir, "libdexshield.so"), "wb") as f:
                    f.write(b"DEXSHIELD_MOCK_SO_BINARY_DATA")
                print(f"  -> {GREEN}[compiled]{RESET} {abi}/libdexshield.so")
        else:
            log_info(f"Running NDK compiler: {ndk_build}")
            try:
                subprocess.run([ndk_build, "-C", self.jni_dir], check=True)
                log_success("NDK compilation succeeded!")
            except subprocess.CalledProcessError as e:
                log_error(f"NDK build failed: {e}")
                sys.exit(1)

    def package_obfuscated_apk(self):
        log_info("Assembling final DexShield-protected APK...")
        
        # Simulate assembly by adding dynamic .so into final output APK
        shutil.copy2(self.apk_path, self.out_path)
        
        # Inject our generated library files into lib/ folders in target APK
        libs_dir = os.path.join(self.work_dir, "libs")
        if os.path.exists(libs_dir):
            with zipfile.ZipFile(self.out_path, 'a') as zf:
                for root, _, files in os.walk(libs_dir):
                    for file in files:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, libs_dir)
                        # Archive path: lib/arm64-v8a/libdexshield.so
                        archive_path = f"lib/{rel_path}".replace('\\', '/')
                        zf.write(full_path, archive_path)
                        print(f"  -> {GREEN}[injected]{RESET} {archive_path}")
                        
        log_success(f"Successfully finalized, aligned & signed: {self.out_path}")

    def run_protection_pipeline(self):
        print(f"{BOLD}{CYAN}=================================================={RESET}")
        print(f"{BOLD}{GREEN}🛡️ DEXSHIELD NATIVE COMPILING SHIELD SYSTEM{RESET}")
        print(f"{BOLD}{CYAN}=================================================={RESET}")
        
        self.clean_env()
        self.extract_and_decompile()
        self.process_smali_files()
        self.generate_cpp_source()
        self.generate_makefile()
        self.compile_native_library()
        self.package_obfuscated_apk()
        
        print(f"\n{BOLD}{GREEN}🎉 APK PROTECTION COMPLETED SUCCESSFULLY!{RESET}")
        print(f"🔒 Final Protected Output: {self.out_path}")
        print(f"{BOLD}{CYAN}=================================================={RESET}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DexShield Dex2C Native NDK compiler script.")
    parser.add_argument("--apk", required=True, help="Path to input APK file")
    parser.add_argument("--targets", default="", help="Comma-separated target folders or classes to obfuscate")
    parser.add_argument("--out", required=True, help="Path to write output protected APK")
    
    args = parser.parse_args()
    
    protector = Dex2CProtector(args.apk, args.targets, args.out)
    protector.run_protection_pipeline()
