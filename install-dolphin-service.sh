#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
launcher_dir="$HOME/.local/bin"
app_data_dir="$HOME/.local/share/dll-assembly-info"
applications_dir="$HOME/.local/share/applications"
cache_dir="$HOME/.cache/dll-assembly-info"
service_dir="$HOME/.local/share/kio/servicemenus"
launcher="$launcher_dir/dll-assembly-info"
installed_gui="$app_data_dir/assembly_info_gui.py"
application_file="$applications_dir/dll-assembly-info.desktop"
service_file="$service_dir/assembly-info.desktop"
python_bin="${PYTHON_BIN:-/usr/bin/python3}"
supported_mime_types="inode/directory;application/vnd.microsoft.portable-executable;application/x-ms-dos-executable;application/x-msdownload;application/x-dosexec;application/x-msdos-program;application/x-executable;application/zip;application/x-zip;application/x-zip-compressed;application/vnd.rar;application/rar;application/x-rar;application/x-rar-compressed;application/x-java-archive;application/vnd.debian.binary-package;application/octet-stream;"

mkdir -p "$launcher_dir" "$app_data_dir" "$applications_dir" "$cache_dir" "$service_dir"
cp "$app_dir/assembly_info_gui.py" "$installed_gui"
chmod +x "$installed_gui"

cat > "$launcher" <<EOF
#!/usr/bin/env bash
set -euo pipefail

output_file="\$(mktemp)"
log_file="$cache_dir/last.log"
result_file="$cache_dir/last-result.txt"
trap 'rm -f "\$output_file"' EXIT

{
    printf '[%s] dll-assembly-info started\n' "\$(date --iso-8601=seconds)"
    printf 'args:'
    printf ' <%s>' "\$@"
    printf '\n'
    printf 'DISPLAY=%s WAYLAND_DISPLAY=%s XDG_SESSION_TYPE=%s\n' "\${DISPLAY-}" "\${WAYLAND_DISPLAY-}" "\${XDG_SESSION_TYPE-}"
} >"\$log_file"

if [[ -t 1 ]]; then
    exec $python_bin "$installed_gui" --text "\$@"
fi

if $python_bin "$installed_gui" "\$@" >>"\$log_file" 2>&1; then
    printf 'qt_gui_status=0\n' >>"\$log_file"
    exit 0
fi
gui_status=\$?
printf 'qt_gui_status=%s\n' "\$gui_status" >>"\$log_file"

if $python_bin "$installed_gui" --text "\$@" >"\$output_file" 2>&1; then
    status=0
else
    status=\$?
fi
cp "\$output_file" "\$result_file"
printf 'text_status=%s\n' "\$status" >>"\$log_file"
cat "\$output_file" >>"\$log_file"

text="\$(cat "\$output_file")"
if command -v kdialog >/dev/null 2>&1; then
    if [[ \${#text} -lt 5000 ]]; then
        kdialog --title "Assembly info" --msgbox "\$text" || true
    else
        kdialog --title "Assembly info" --textbox "\$output_file" 760 460 || true
    fi
elif command -v zenity >/dev/null 2>&1; then
    zenity --title "Assembly info" --text-info --width 760 --height 460 --filename "\$output_file" || true
else
    notify-send "Assembly info" "\$(head -c 220 "\$output_file")"
fi

exit "\$status"
EOF
chmod +x "$launcher"

cat > "$service_file" <<EOF
[Desktop Entry]
Type=Service
Name=Assembly info
X-KDE-ServiceTypes=KonqPopupMenu/Plugin
MimeType=$supported_mime_types
Actions=assemblyInfo;
X-KDE-Priority=TopLevel

[Desktop Action assemblyInfo]
Name=Assembly info
Name[fr]=Assembly info
Icon=dialog-information
Exec=$launcher %U
EOF
chmod +x "$service_file"

cat > "$application_file" <<EOF
[Desktop Entry]
Type=Application
Name=Assembly info
Name[fr]=Assembly info
Comment=Show .NET assembly name and version
Comment[fr]=Afficher le nom et la version d'une assembly .NET
Icon=dialog-information
Exec=$launcher %U
Terminal=false
Categories=Utility;
MimeType=$supported_mime_types
EOF
chmod +x "$application_file"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$applications_dir" >/dev/null 2>&1 || true
fi
if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 >/dev/null 2>&1 || true
elif command -v kbuildsycoca5 >/dev/null 2>&1; then
    kbuildsycoca5 >/dev/null 2>&1 || true
fi

echo "Menu Dolphin installe: $service_file"
echo "Ferme et rouvre Dolphin si l'option n'apparait pas tout de suite."
