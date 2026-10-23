# LinkedIn Post Draft

Are you developing on Windows with WSL2 but tired of the **10x filesystem lag** between the host and Linux layers? 

When Google's Antigravity IDE upgraded to 2.0, the restructured editor interface broke the traditional WSL Remote Plugin workflow for many developers. We were faced with a frustrating compromise: move code back to slow Windows host disks, or deal with network path configurations that break local terminal runners and modern developer tools.

To solve this, I built and open-sourced **AnyLink** 🚀

📸 *[Attach Image 2: WSL Linked Desktop Application GUI]*

🔗 **GitHub Repository**: https://github.com/fauzulkc/AnyLink

### What is AnyLink?
AnyLink is a lightweight, zero-dependency Windows desktop application (built with Python & CustomTkinter) that maps your high-performance WSL2 Linux directories to local Windows Directory Symbolic Links.

### Why this is a game-changer for AI Agentic Workflows:
With the rise of local AI agents like **Claude Desktop**, **Antigravity 2.0**, and Model Context Protocol (MCP) servers, we need our host-side AI tools to read, write, and watch files dynamically. 
Many of these agents struggle with network UNC paths (`\\wsl.localhost\...`), causing terminal commands, file watch systems, and MCP configurations to crash.

📸 *[Attach Image 1: WSL-Linker Linked Folder being used in Claude Desktop]*

AnyLink translates these directories into standard local paths (e.g., `D:\projects\my-app`). The Windows host agent sees a native local folder, while the source code remains physically on the WSL `ext4` partition, building and compiling at native Linux speeds.

### Key Features:
* ⚡ **Zero-Latency Sync**: No disk duplication or sync delays.
* 🐳 **Reverse Docker Sandboxes (Experimental Suite)**: Run 100% isolated Docker dev containers with zero host bind mounts. Container files are reverse-mounted via WSL SSHFS and linked to Windows with a self-healing reconnection daemon that recovers across restarts.
* 🛡️ **Safe Unlinking**: Built-in safeguards that untether the symbolic link without touching your target Linux files.
* 📦 **Zero Dependencies**: Available as a standalone, single-file compiled EXE (runs instantly without Python installed).
* 🔧 **CLI Support**: Features a proxy runner (`anylink run <cmd>`) to execute Linux commands directly from Windows shells.
* 🛠️ **WSL Launcher Wrapper**: Includes an advanced context-aware shell launcher wrapper to restore the `antigravity` command inside WSL terminals.

Check out the repo, grab the compiled release, and let's keep cross-OS development fast, fluid, and agent-ready!

#WSL2 #SoftwareEngineering #OpenSource #AIAgents #Python #WindowsDev #AnyLink\n