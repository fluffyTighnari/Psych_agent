#!/bin/sh
echo "=== containerd env ==="
cat /proc/101/environ 2>/dev/null | tr '\0' '\n' | grep -i proxy || echo "(no proxy env)"
echo "=== grep 10809 in VM config/data dirs ==="
grep -rn "10809" /etc /run /var/lib/containerd 2>/dev/null --include="*.toml" --include="*.json" --include="*.conf" --include="*.yaml" | head -20
echo "=== done ==="