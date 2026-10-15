// Stateless protocol adapter over the pinned Semantix lexical index.
package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"unicode/utf8"

	"semantix/kernel/bm25"
	"semantix/kernel/slice"
)

const protocol = "zhongan-memory-rank-v1"
const upstream = "5e546dcb69b7545e9fba9f95f9464c0ddd6f9cff"

type document struct {
	ID      string `json:"id"`
	Content string `json:"content"`
}
type request struct {
	Protocol  string     `json:"protocol"`
	RequestID string     `json:"request_id"`
	Query     string     `json:"query"`
	Documents []document `json:"documents"`
}
type hit struct {
	ID       string  `json:"id"`
	Score    float64 `json:"score"`
	Coverage float64 `json:"coverage"`
}
type response struct {
	Protocol  string `json:"protocol"`
	RequestID string `json:"request_id"`
	Upstream  string `json:"upstream"`
	Retriever string `json:"retriever"`
	Hits      []hit  `json:"hits"`
}

func rank(r request) (response, error) {
	out := response{Protocol: protocol, RequestID: r.RequestID, Upstream: upstream, Retriever: "semantix-bm25", Hits: []hit{}}
	if r.Protocol != protocol || len(r.RequestID) == 0 || len(r.RequestID) > 100 ||
		utf8.RuneCountInString(r.Query) > 4000 || len(r.Documents) > 256 {
		return out, errors.New("invalid request")
	}
	index := bm25.New() // No persistent state and no discovery of a global user store.
	seen := map[string]bool{}
	for _, d := range r.Documents {
		if d.ID == "" || len(d.ID) > 100 || seen[d.ID] || utf8.RuneCountInString(d.Content) > 1000 {
			return out, errors.New("invalid document")
		}
		seen[d.ID] = true
		if len(bm25.Tokenize(d.Content)) == 0 {
			continue
		}
		if err := index.Insert(&slice.Slice{ID: d.ID, Scope: slice.Project, Type: slice.Memory, Content: []byte(d.Content)}); err != nil {
			return out, errors.New("index unavailable")
		}
	}
	if len(bm25.Tokenize(r.Query)) == 0 {
		return out, nil
	}
	hits, err := index.Search(r.Query, 256, slice.Project)
	if err != nil {
		return out, errors.New("retrieval unavailable")
	}
	for _, h := range hits {
		out.Hits = append(out.Hits, hit{ID: h.Slice.ID, Score: h.Score, Coverage: bm25.QueryCoverage(r.Query, string(h.Slice.Content))})
	}
	return out, nil
}

func run(in io.Reader, out io.Writer) error {
	decoder := json.NewDecoder(io.LimitReader(in, 2*1024*1024))
	decoder.DisallowUnknownFields()
	var r request
	if err := decoder.Decode(&r); err != nil {
		return errors.New("invalid protocol")
	}
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		return errors.New("trailing input")
	}
	result, err := rank(r)
	if err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(result)
}

func main() {
	if err := run(os.Stdin, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "memory rank request rejected") // Never echo input text.
		os.Exit(1)
	}
}
