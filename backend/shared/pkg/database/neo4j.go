// Package database provides shared database connection factories used by all
// Go microservices. This file owns the Neo4j driver lifecycle.
//
// Usage (from any service):
//
//	driver, err := database.NewNeo4jDriver(cfg)
//	defer driver.Close(ctx)
//	repo := neo4j_repo.New(driver)
package database

import (
	"context"
	"fmt"
	"time"

	"github.com/neo4j/neo4j-go-driver/v5/neo4j"
)

// Neo4jConfig holds all connection parameters. Loaded from environment
// variables via the shared config package.
type Neo4jConfig struct {
	URI      string // e.g. bolt://localhost:7687  or  neo4j://neo4j:7687
	Username string
	Password string

	// Connection pool tuning. Defaults are safe for a single-service dev setup.
	MaxConnectionPoolSize    int           // default: 50
	ConnectionAcquisitionTimeout time.Duration // default: 60s
	MaxTransactionRetryTime  time.Duration // default: 30s
}

// DefaultNeo4jConfig returns sane defaults for local development.
// Override individual fields before passing to NewNeo4jDriver.
func DefaultNeo4jConfig() Neo4jConfig {
	return Neo4jConfig{
		URI:                          "bolt://localhost:7687",
		Username:                     "neo4j",
		Password:                     "devpassword",
		MaxConnectionPoolSize:        50,
		ConnectionAcquisitionTimeout: 60 * time.Second,
		MaxTransactionRetryTime:      30 * time.Second,
	}
}

// NewNeo4jDriver creates a thread-safe Neo4j driver and verifies connectivity.
// The driver is designed to be created once at startup and shared across the
// entire service via dependency injection.
//
// The caller is responsible for calling driver.Close(ctx) on shutdown.
func NewNeo4jDriver(cfg Neo4jConfig) (neo4j.DriverWithContext, error) {
	driver, err := neo4j.NewDriverWithContext(
		cfg.URI,
		neo4j.BasicAuth(cfg.Username, cfg.Password, ""),
		func(c *neo4j.Config) {
			c.MaxConnectionPoolSize = cfg.MaxConnectionPoolSize
			c.ConnectionAcquisitionTimeout = cfg.ConnectionAcquisitionTimeout
			c.MaxTransactionRetryTime = cfg.MaxTransactionRetryTime
		},
	)
	if err != nil {
		return nil, fmt.Errorf("neo4j: failed to create driver: %w", err)
	}

	// Verify the connection is live before returning.
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := driver.VerifyConnectivity(ctx); err != nil {
		_ = driver.Close(ctx)
		return nil, fmt.Errorf("neo4j: connectivity check failed (is Neo4j running?): %w", err)
	}

	return driver, nil
}

// NewNeo4jSession opens a new session from the driver.
// Sessions are lightweight and should be created per-operation, not shared.
// Always defer session.Close(ctx) after calling this.
//
// Example:
//
//	session := database.NewNeo4jSession(ctx, driver, neo4j.AccessModeWrite)
//	defer session.Close(ctx)
func NewNeo4jSession(
	ctx context.Context,
	driver neo4j.DriverWithContext,
	mode neo4j.AccessMode,
) neo4j.SessionWithContext {
	return driver.NewSession(ctx, neo4j.SessionConfig{
		AccessMode: mode,
	})
}