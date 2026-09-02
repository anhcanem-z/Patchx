import sys
from patchx_core.behavior.frida_generator import main as frida_main

def print_usage():
    print("Usage: python3 _patchx <module> [args]")
    print("Modules:")
    print("  frida    Chạy Frida Script Generator")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    module_name = sys.argv[1].lower()
    
    # Loại bỏ tham số đầu tiên ('frida') để trả sys.argv về đúng tham số của module đó
    sys.argv.pop(1)

    if module_name == "frida":
        frida_main()
    else:
        print(f"[-] Unknown module: {module_name}")
        print_usage()
