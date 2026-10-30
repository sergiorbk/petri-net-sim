import { describe, expect, it } from "vitest";
import { imageRegion } from "./ReviewCanvas";
import type { BundleInfo } from "@/lib/training-client";

describe("Review regions use exact stored image coordinates", () => {
    const info = {
        image_sha256: "a".repeat(64),
        geometry: {
            transform: { origin_x: -50, origin_y: 20, scale: 2 },
            image: { width: 1000, height: 600 },
        },
    } as BundleInfo;
    it("converts a reversed live-canvas drag and binds the exact image", () => {
        expect(imageRegion(info, { x: 150, y: 120 }, { x: 50, y: 70 })).toEqual(
            {
                coordinate_system: "image-pixels",
                image_sha256: "a".repeat(64),
                x: 200,
                y: 100,
                width: 200,
                height: 100,
            },
        );
    });
    it("clips to the image, rejecting empty areas or missing evidence", () => {
        expect(
            imageRegion(info, { x: -100, y: 0 }, { x: 1000, y: 1000 }),
        ).toMatchObject({ x: 0, y: 0, width: 1000, height: 600 });
        expect(
            imageRegion(info, { x: -1000, y: -1000 }, { x: -900, y: -900 }),
        ).toBeUndefined();
        expect(
            imageRegion(
                { ...info, image_sha256: null },
                { x: 0, y: 0 },
                { x: 1, y: 1 },
            ),
        ).toBeUndefined();
    });
});
