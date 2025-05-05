GEM5_PATH = $(realpath /home/phadnis/ece757_final_proj)
TARGET_ISA = riscv
CC = riscv64-unknown-linux-gnu-gcc
CFLAGS = -static
CFLAGS += -I$(GEM5_PATH)/include
LDFLAGS += -L$(GEM5_PATH)/util/m5/build/$(TARGET_ISA)/out -lm5

TARGET = lax

SRC = lax_read_array.c

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f $(TARGET)
