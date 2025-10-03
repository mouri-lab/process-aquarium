#!/usr/bin/env python3
"""
Verification script for Process Aquarium backends
Tests both Pyglet (GPU-accelerated) and Pygame (fallback) backends
"""
import platform
import sys
import os

print("=== Process Aquarium Backend Verification ===")
print(f"Platform: {platform.system()}")
print(f"Python: {sys.version}")

# Import the Aquarium class
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_pyglet_backend():
    """Test the Pyglet GPU-accelerated backend"""
    print("\n--- Testing Pyglet Backend (GPU-accelerated) ---")
    
    # Set backend to pyglet
    os.environ['AQUARIUM_BACKEND'] = 'pyglet'
    
    # Import after setting env var
    from src.visuals import Aquarium
    
    try:
        print("Creating headless aquarium...")
        aquarium = Aquarium(width=100, height=100, headless=True, headless_interval=1.0)
        
        print("✅ Pyglet backend initialized successfully")
        print(f"  - Width: {aquarium.width}, Height: {aquarium.height}")
        print(f"  - Headless: {aquarium.headless}")
        
        print("Testing process data update...")
        aquarium.update_process_data()
        print(f"✅ Process data updated - {len(aquarium.fishes)} fish created")
        
        return True
    except Exception as e:
        print(f"❌ Pyglet backend test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_pygame_backend():
    """Test the Pygame fallback backend"""
    print("\n--- Testing Pygame Backend (Fallback) ---")
    
    # Set backend to pygame
    os.environ['AQUARIUM_BACKEND'] = 'pygame'
    
    # Remove cached imports
    for mod in list(sys.modules.keys()):
        if 'src.visuals' in mod:
            del sys.modules[mod]
    
    try:
        # Try to import pygame first
        try:
            import pygame
            pygame_available = True
        except ImportError:
            pygame_available = False
            print("⚠️  Pygame not installed - skipping pygame backend test")
            return None
        
        from src.visuals import Aquarium
        
        print("Creating headless aquarium with pygame...")
        aquarium = Aquarium(width=100, height=100, headless=True, headless_interval=1.0)
        
        print("✅ Pygame backend initialized successfully")
        print(f"  - Width: {aquarium.width}, Height: {aquarium.height}")
        print(f"  - Headless: {aquarium.headless}")
        
        return True
    except Exception as e:
        print(f"❌ Pygame backend test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("Running Backend Tests")
    print("=" * 60)
    
    results = {}
    
    # Test Pyglet backend (default)
    results['pyglet'] = test_pyglet_backend()
    
    # Test Pygame backend (fallback)
    results['pygame'] = test_pygame_backend()
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for backend, result in results.items():
        if result is True:
            print(f"✅ {backend.capitalize()} backend: PASSED")
        elif result is False:
            print(f"❌ {backend.capitalize()} backend: FAILED")
        else:
            print(f"⚠️  {backend.capitalize()} backend: SKIPPED")
    
    # Exit with appropriate code
    if results['pyglet'] is True:
        print("\n🎉 Primary backend (Pyglet) is working!")
        return 0
    else:
        print("\n❌ Primary backend (Pyglet) failed!")
        return 1


if __name__ == "__main__":
    exit(main())
