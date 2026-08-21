# Frida trên Termux — nạp trước libpython3.14.so (RTLD_GLOBAL) để binding
# frida 17.9.10 (build cũ) tìm thấy symbol _Py_NoneStruct.
# Dùng:  source tools/frida_env.sh   (trong mọi phiên cần frida)
# hoặc:  LD_PRELOAD=libpython3.14.so frida-ps -U
export LD_PRELOAD=libpython3.14.so
