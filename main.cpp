#include <fstream>
#include <iostream>
#include <unistd.h>
#include <vector>

#include <sqlite3.h>

#include "parser.h"

#ifdef FUZZING_BUILD
__AFL_FUZZ_INIT();
#endif

static void exec(sqlite3 *db, const char *sql) {
    sqlite3_exec(db, sql, nullptr, nullptr, nullptr);
}

static void run_command(sqlite3 *db, const CommandStruct &cmd) {
    char sql[512];
    switch (cmd.type) {
        case Add: {
            int32_t n = std::get<addArgs>(cmd.arguments).number;
            snprintf(sql, sizeof(sql), "INSERT INTO t(val) VALUES(%d)", n);
            exec(db, sql);
            break;
        }
        case Remove: {
            const auto &args = std::get<removeArgs>(cmd.arguments);
            for (int32_t n : args.numbers) {
                if (args.allOccurrences)
                    snprintf(sql, sizeof(sql), "DELETE FROM t WHERE val=%d", n);
                else
                    snprintf(sql, sizeof(sql),
                             "DELETE FROM t WHERE rowid="
                             "(SELECT rowid FROM t WHERE val=%d LIMIT 1)", n);
                exec(db, sql);
            }
            break;
        }
        case Divide: {
            double d = std::get<divideArgs>(cmd.arguments).divisor;
            // proto guarantees d >= 0.01 (random_command loops until d > 0.01)
            snprintf(sql, sizeof(sql),
                     "UPDATE t SET val=CAST(val/%.10f AS INTEGER)", d);
            exec(db, sql);
            break;
        }
        case Reset:
            exec(db, "DELETE FROM t");
            break;
        case Print: {
            // Exercises SQLite's expression evaluator + aggregate path
            sqlite3_stmt *stmt = nullptr;
            sqlite3_prepare_v2(
                db, "SELECT val, val*val, ABS(val) FROM t ORDER BY val", -1, &stmt, nullptr);
            while (sqlite3_step(stmt) == SQLITE_ROW) { /* consume rows */ }
            sqlite3_finalize(stmt);
            break;
        }
        case InvalidCommand:
            break;
    }
}

// Bug 1: sum==42 with count>=3; Bug 2: ssq%1000==133 with count>=4
static void check_crashes(sqlite3 *db) {
    sqlite3_stmt *stmt = nullptr;
    int rc = sqlite3_prepare_v2(
        db,
        "SELECT SUM(val), COUNT(*), SUM(val*val) FROM t",
        -1, &stmt, nullptr);
    if (rc != SQLITE_OK) return;

    if (sqlite3_step(stmt) == SQLITE_ROW &&
        sqlite3_column_type(stmt, 0) != SQLITE_NULL) {
        int64_t sum   = sqlite3_column_int64(stmt, 0);
        int64_t count = sqlite3_column_int64(stmt, 1);
        int64_t ssq   = sqlite3_column_int64(stmt, 2);
        sqlite3_finalize(stmt);

        if (sum == 42 && count >= 3) {
            std::cerr << "Bug 1: sum==42 with count==" << count << "\n";
            abort();
        }
        if (count >= 4 && (ssq % 1000) == 133) {
            std::cerr << "Bug 2: ssq%1000==133 with count==" << count << "\n";
            abort();
        }
    } else {
        sqlite3_finalize(stmt);
    }
}

static void simulate(const unsigned char *buf, size_t len) {
    auto commands = parser::parseCommands(buf, len);
    if (commands.empty()) return;

    sqlite3 *db = nullptr;
    sqlite3_open(":memory:", &db);
    exec(db, "CREATE TABLE t(val INTEGER)");
    exec(db, "PRAGMA journal_mode=OFF");  // faster in-memory, more code paths

    for (const auto &cmd : commands)
        run_command(db, cmd);

    check_crashes(db);
    sqlite3_close(db);
}

int main(int argc, char *argv[]) {
#ifndef FUZZING_BUILD
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <inputfile>\n";
        return 1;
    }
    std::ifstream f(argv[1], std::ios::binary);
    std::vector<unsigned char> buf(
        (std::istreambuf_iterator<char>(f)), {});
    simulate(buf.data(), buf.size());
#else
    __AFL_INIT();
    unsigned char *buf = __AFL_FUZZ_TESTCASE_BUF;
    while (__AFL_LOOP(10000)) {
        ssize_t len = __AFL_FUZZ_TESTCASE_LEN;
        simulate(buf, static_cast<size_t>(len < 0 ? 0 : len));
    }
#endif
    return 0;
}
