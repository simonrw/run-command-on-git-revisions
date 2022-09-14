package main

import (
	"flag"
	"fmt"
	"log"
	"os"

	"github.com/go-git/go-git/v5"
)

func runCommandOnGitRevisions(start string, end string, path string, args []string) error {
	repo, err := git.PlainOpen(path)
	if err != nil {
		return fmt.Errorf("opening repo: %w", err)
	}
	_ = repo
	return nil
}

func main() {
	var startFlag = flag.String("s", "", "start rev")
	var endFlag = flag.String("e", "", "end rev")
	var pathFlag = flag.String("p", "", "specific path")
	flag.Parse()

	if *startFlag == "" {
		log.Fatalf("start flag missing")
	}

	if *endFlag == "" {
		*endFlag = "HEAD"
	}

	if *pathFlag == "" {
		here, err := os.Getwd()
		if err != nil {
			log.Fatalf("error getting cwd: %v", err)
			*pathFlag = here
		}
	}

	args := flag.Args()
	if len(args) == 0 {
		log.Fatalf("no command specified")
	}

	if err := runCommandOnGitRevisions(*startFlag, *endFlag, *pathFlag, args); err != nil {
		log.Fatal(err)
	}
}
