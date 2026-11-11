// Fixed local network control. It never uses credentials or remote endpoints.
package main

import (
	"fmt"
	"net"
	"os"
	"os/user"
	"strconv"
	"strings"
	"time"
)

func main() {
	if len(os.Args) == 2 && os.Args[1] == "--identity" {
		current, err := user.Current()
		if err != nil {
			os.Exit(65)
		}
		name := strings.ToLower(current.Username)
		name = name[strings.LastIndexAny(name, `\/`)+1:]
		switch name {
		case "codexsandboxoffline":
			fmt.Println("REFLOW_IDENTITY_OFFLINE")
		case "codexsandboxonline":
			fmt.Println("REFLOW_IDENTITY_ONLINE")
		default:
			fmt.Println("REFLOW_IDENTITY_OTHER")
		}
		return
	}
	if len(os.Args) != 2 {
		os.Exit(64)
	}
	host, port, err := net.SplitHostPort(os.Args[1])
	number, numberErr := strconv.Atoi(port)
	if err != nil || numberErr != nil || host != "127.0.0.1" || number < 1 || number > 65535 {
		os.Exit(64)
	}
	conn, err := net.DialTimeout("tcp4", os.Args[1], 2*time.Second)
	if err != nil {
		fmt.Println("REFLOW_NETWORK_BLOCKED")
		os.Exit(42)
	}
	_ = conn.Close()
	fmt.Println("REFLOW_NETWORK_REACHABLE")
}
