export function adjustGalleryActiveIndex(
  activeIndex: number,
  removedSlideIndex: number,
  nextSlideCount: number,
): number {
  if (nextSlideCount <= 0) return 0;
  let next = activeIndex;
  if (removedSlideIndex < activeIndex) {
    next = activeIndex - 1;
  }
  return Math.min(Math.max(0, next), nextSlideCount - 1);
}
