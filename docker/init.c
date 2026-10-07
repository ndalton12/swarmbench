/* Minimal PID 1: reaps orphaned processes and exits on SIGTERM/SIGINT. */
#include <signal.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

static void on_child(int sig) { (void)sig; }
static void on_term(int sig) { (void)sig; _exit(0); }

int main(void) {
    signal(SIGCHLD, on_child);
    signal(SIGTERM, on_term);
    signal(SIGINT, on_term);
    for (;;) {
        while (waitpid(-1, NULL, WNOHANG) > 0) {
        }
        pause();
    }
}
