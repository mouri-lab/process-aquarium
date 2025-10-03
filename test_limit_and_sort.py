#!/usr/bin/env python3
"""
Test script for process limiting and sorting functionality.
"""

from src.core.process_manager import ProcessManager
import time


def test_basic_functionality():
    """Test basic ProcessManager functionality"""
    print("=== Test 1: Basic ProcessManager ===")
    pm = ProcessManager()
    pm.update()
    time.sleep(0.5)
    
    total_processes = len(pm.processes)
    print(f"Total processes detected: {total_processes}")
    assert total_processes > 0, "Should detect at least some processes"
    print("✓ Basic functionality works\n")


def test_process_limiting():
    """Test process limiting"""
    print("=== Test 2: Process Limiting ===")
    pm = ProcessManager()
    
    # Test with limit of 5
    pm.set_process_limit(5)
    pm.update()
    time.sleep(0.5)
    
    displayed_count = len(pm.processes)
    print(f"Limit set to 5, displayed processes: {displayed_count}")
    assert displayed_count <= 5, f"Expected <= 5 processes, got {displayed_count}"
    print("✓ Process limiting works\n")


def test_sorting_by_memory():
    """Test sorting by memory"""
    print("=== Test 3: Sorting by Memory (descending) ===")
    pm = ProcessManager()
    pm.set_process_limit(10)
    pm.set_sort_config('memory', 'desc')
    pm.update()
    time.sleep(0.5)
    
    processes = list(pm.processes.values())
    if len(processes) >= 2:
        # Check if processes are sorted by memory in descending order
        for i in range(len(processes) - 1):
            assert processes[i].memory_percent >= processes[i + 1].memory_percent, \
                f"Memory not sorted correctly: {processes[i].memory_percent} < {processes[i + 1].memory_percent}"
        
        print("Top 5 processes by memory:")
        for proc in processes[:5]:
            print(f"  PID {proc.pid}: {proc.name} - {proc.memory_percent:.2f}%")
        print("✓ Memory sorting works\n")
    else:
        print("⚠ Not enough processes to verify sorting\n")


def test_sorting_by_cpu():
    """Test sorting by CPU"""
    print("=== Test 4: Sorting by CPU (descending) ===")
    pm = ProcessManager()
    pm.set_process_limit(10)
    pm.set_sort_config('cpu', 'desc')
    pm.update()
    time.sleep(0.5)
    
    processes = list(pm.processes.values())
    if len(processes) >= 2:
        # Check if processes are sorted by CPU in descending order
        for i in range(len(processes) - 1):
            assert processes[i].cpu_percent >= processes[i + 1].cpu_percent, \
                f"CPU not sorted correctly: {processes[i].cpu_percent} < {processes[i + 1].cpu_percent}"
        
        print("Top 5 processes by CPU:")
        for proc in processes[:5]:
            print(f"  PID {proc.pid}: {proc.name} - {proc.cpu_percent:.2f}%")
        print("✓ CPU sorting works\n")
    else:
        print("⚠ Not enough processes to verify sorting\n")


def test_sorting_by_name():
    """Test sorting by name"""
    print("=== Test 5: Sorting by Name (ascending) ===")
    pm = ProcessManager()
    pm.set_process_limit(10)
    pm.set_sort_config('name', 'asc')
    pm.update()
    time.sleep(0.5)
    
    processes = list(pm.processes.values())
    if len(processes) >= 2:
        # Check if processes are sorted by name in ascending order
        for i in range(len(processes) - 1):
            assert processes[i].name.lower() <= processes[i + 1].name.lower(), \
                f"Name not sorted correctly: {processes[i].name} > {processes[i + 1].name}"
        
        print("First 5 processes by name:")
        for proc in processes[:5]:
            print(f"  PID {proc.pid}: {proc.name}")
        print("✓ Name sorting works\n")
    else:
        print("⚠ Not enough processes to verify sorting\n")


def test_sorting_by_pid():
    """Test sorting by PID"""
    print("=== Test 6: Sorting by PID (ascending) ===")
    pm = ProcessManager()
    pm.set_process_limit(10)
    pm.set_sort_config('pid', 'asc')
    pm.update()
    time.sleep(0.5)
    
    processes = list(pm.processes.values())
    if len(processes) >= 2:
        # Check if processes are sorted by PID in ascending order
        for i in range(len(processes) - 1):
            assert processes[i].pid <= processes[i + 1].pid, \
                f"PID not sorted correctly: {processes[i].pid} > {processes[i + 1].pid}"
        
        print("First 5 processes by PID:")
        for proc in processes[:5]:
            print(f"  PID {proc.pid}: {proc.name}")
        print("✓ PID sorting works\n")
    else:
        print("⚠ Not enough processes to verify sorting\n")


def test_dynamic_configuration_changes():
    """Test dynamic configuration changes"""
    print("=== Test 7: Dynamic Configuration Changes ===")
    pm = ProcessManager()
    
    # Start with limit of 20, sort by memory
    pm.set_process_limit(20)
    pm.set_sort_config('memory', 'desc')
    pm.update()
    time.sleep(0.5)
    print(f"Config 1: Limit=20, sort by memory → {len(pm.processes)} processes")
    
    # Change to limit of 5, sort by CPU
    pm.set_process_limit(5)
    pm.set_sort_config('cpu', 'desc')
    pm.update()
    time.sleep(0.5)
    print(f"Config 2: Limit=5, sort by CPU → {len(pm.processes)} processes")
    assert len(pm.processes) <= 5, "Should respect new limit"
    
    # Remove limit, sort by name
    pm.set_process_limit(None)
    pm.set_sort_config('name', 'asc')
    pm.update()
    time.sleep(0.5)
    print(f"Config 3: No limit, sort by name → {len(pm.processes)} processes")
    
    print("✓ Dynamic configuration changes work\n")


def main():
    """Run all tests"""
    print("=" * 60)
    print("Testing Process Limiting and Sorting Functionality")
    print("=" * 60 + "\n")
    
    try:
        test_basic_functionality()
        test_process_limiting()
        test_sorting_by_memory()
        test_sorting_by_cpu()
        test_sorting_by_name()
        test_sorting_by_pid()
        test_dynamic_configuration_changes()
        
        print("=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
