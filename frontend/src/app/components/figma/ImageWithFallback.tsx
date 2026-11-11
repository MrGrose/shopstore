import React, { useEffect, useState } from "react";

type ImageWithFallbackProps = React.ImgHTMLAttributes<HTMLImageElement> & {
  fallbackSrc?: string | null;
  onExhausted?: () => void;
  placeholderSrc?: string | null;
};

export function ImageWithFallback({
  fallbackSrc,
  onExhausted,
  placeholderSrc,
  src,
  alt,
  style,
  className,
  ...rest
}: ImageWithFallbackProps) {
  const [currentSrc, setCurrentSrc] = useState(src);
  const [didError, setDidError] = useState(false);
  const [removedAfterExhaustion, setRemovedAfterExhaustion] = useState(false);

  useEffect(() => {
    setCurrentSrc(src);
    setDidError(false);
    setRemovedAfterExhaustion(false);
  }, [src, fallbackSrc]);

  const handleError = () => {
    if (fallbackSrc && currentSrc !== fallbackSrc) {
      setCurrentSrc(fallbackSrc);
      return;
    }
    onExhausted?.();
    if (placeholderSrc) {
      setDidError(true);
      return;
    }
    setRemovedAfterExhaustion(true);
  };

  if (removedAfterExhaustion) {
    return null;
  }

  if (didError && placeholderSrc) {
    return (
      <img
        src={placeholderSrc}
        alt={alt}
        className={className}
        style={style}
        {...rest}
        data-image-placeholder="true"
      />
    );
  }

  return (
    <img
      src={currentSrc}
      alt={alt}
      className={className}
      style={style}
      {...rest}
      onError={handleError}
    />
  );
}
